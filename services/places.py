"""Клиент OpenStreetMap Overpass API — поиск компаний по городу и категории.

Бесплатно, без ключей. Лимит результатов MAX_LIMIT — без него Overpass
может вернуть тысячи строк и повесить бота.
Результаты кэшируются в памяти на CACHE_TTL_SECONDS (PERF-1).
"""

import asyncio
import email.utils
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_LIMIT = 60
REQUEST_TIMEOUT_SECONDS = 40
# TTL кэша результатов Overpass в секундах (PERF-1).
# Повторный запрос того же города+категории в течение этого времени не идёт в сеть.
CACHE_TTL_SECONDS = 1800  # 30 минут

# Простой in-memory кэш: ключ -> (timestamp, результат)
_overpass_cache: OrderedDict[str, tuple[float, list]] = OrderedDict()
_inflight: dict[str, asyncio.Task] = {}
_inflight_lock = asyncio.Lock()
_request_semaphore: asyncio.Semaphore | None = None
_request_semaphore_loop = None


def _get_request_semaphore() -> asyncio.Semaphore:
    global _request_semaphore, _request_semaphore_loop
    loop = asyncio.get_running_loop()
    if _request_semaphore is None or _request_semaphore_loop is not loop:
        from config import settings

        _request_semaphore = asyncio.Semaphore(max(1, settings.overpass_max_concurrency))
        _request_semaphore_loop = loop
    return _request_semaphore

# Категории бизнеса -> OSM-теги (key, value)
CATEGORIES: dict[str, tuple[str, str, str]] = {
    # slug: (label, tag_key, tag_value)
    "barber": ("Барбершоп / Парикмахерская", "shop", "hairdresser"),
    "beauty": ("Салон красоты", "shop", "beauty"),
    "cafe": ("Кафе", "amenity", "cafe"),
    "restaurant": ("Ресторан", "amenity", "restaurant"),
    "fitness": ("Фитнес-клуб", "leisure", "fitness_centre"),
    "dentist": ("Стоматология", "amenity", "dentist"),
    "car_repair": ("Автосервис", "shop", "car_repair"),
    "florist": ("Магазин цветов", "shop", "florist"),
}


class PlacesError(Exception):
    """Любая ошибка при обращении к Overpass (сеть, таймаут, HTTP 4xx/5xx, плохой JSON)."""


@dataclass
class Company:
    name: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "address": self.address,
            "phone": self.phone,
            "website": self.website,
        }


def _sanitize_ql(value: str) -> str:
    """Whitelist-фильтр для значений, подставляемых в Overpass QL (S-1).

    Разрешаем только символы, встречающиеся в реальных топонимах:
    буквы (любые Unicode), цифры, пробел, дефис, точку, апостроф, скобки
    (для «Ростов-на-Дону», «Нур-Султан», «Алма-Ата» и т.п.).
    Всё остальное — удаляем. Это надёжнее blacklist: новые QL-спецсимволы
    (;, {, }, ->, .a и т.д.) не попадут в запрос автоматически.
    """
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
                  "0123456789 -.'()")
    return "".join(ch for ch in value if ch in allowed)


class _RetryablePlacesError(Exception):
    def __init__(self, status: int, delay: float | None = None):
        self.status = status
        self.delay = delay


# Служебные слова, которые OSM держит в НИЖНЕМ регистре внутри составных
# названий городов: «Ростов-на-Дону», «Комсомольск-на-Амуре», «Рио-де-Жанейро».
# str.title() ошибочно капитализирует их ("Ростов-На-Дону") -> area["name"=...]
# не находится -> поиск возвращает 0 объектов при HTTP 200 (тот же класс бага,
# что и с «астаной», только всплывает на конкретных городах). Первое слово
# названия НЕ трогаем — только внутренние токены.
_CITY_LOWER_CONNECTORS: frozenset[str] = frozenset({
    # русские предлоги в топонимах
    "на", "над", "под", "по", "при", "у", "за",
    # частые транслитерации иностранных названий
    "де", "ла", "ле", "дель", "ди", "да", "дю", "дос", "лос", "лас", "эль",
})

# Токены-слова между разделителями (пробел/дефис). Разделители сохраняем.
_CITY_TOKEN_SPLIT = re.compile(r"([ \-])")


def normalize_city(city: str) -> str:
    """Приводит регистр названия города к тому, как его хранит OSM.

    Overpass сравнивает area["name"="..."] РЕГИСТРОЗАВИСИМО, а OSM хранит
    города в «Заглавном Виде Слов» ("Астана", "Нижний Новгород"). Пользователь
    вводит как угодно ("астана", "АСТАНА") — и без нормализации area просто не
    находится: запрос отрабатывает штатно (HTTP 200), но возвращает 0 объектов,
    из-за чего бот молча отвечает «ничего не нашлось». Это и был реальный баг с
    городом «астана».

    База — str.title() (каждое слово с заглавной через пробелы/дефисы), но затем
    служебные слова из _CITY_LOWER_CONNECTORS внутри названия возвращаются в
    нижний регистр: OSM хранит «Ростов-на-Дону», а не «Ростов-На-Дону», и точный
    поиск по неверному регистру давал 0 результатов (реальный баг, найденный на
    живом прогоне). Первое слово всегда с заглавной — «На…» как начало названия
    не встречается.
    """
    titled = city.strip().title()
    tokens = _CITY_TOKEN_SPLIT.split(titled)
    first_word_done = False
    for i, tok in enumerate(tokens):
        if tok in (" ", "-") or tok == "":
            continue
        if first_word_done and tok.lower() in _CITY_LOWER_CONNECTORS:
            tokens[i] = tok.lower()
        first_word_done = True
    return "".join(tokens)


# Ключи имени, по которым ищем город. OSM хранит основной name на локальном
# языке: для многих городов Казахстана это казахский («name»=«Өскемен» для
# Усть-Каменогорска), а русское/английское имя лежит в name:ru / name:en.
# Поиск только по «name» давал 0 результатов на реальном вводе «Усть-Каменогорск»
# (в области при этом 75 кафе). Объединяем area по всем трём ключам в один набор.
_CITY_NAME_KEYS: tuple[str, ...] = ("name", "name:ru", "name:en")


def build_query(city: str, tag_key: str, tag_value: str) -> str:
    # Регистр -> как в OSM (иначе area не находится), затем чистим QL-опасные символы.
    safe_city = _sanitize_ql(normalize_city(city))
    # Объединение area-выражений по разным ключам имени в ОДИН набор .a: даже если
    # город матчится и по name, и по name:ru, area-set схлопнёт дубликат области,
    # поэтому объекты не задваиваются (тело запроса выполняется по .a один раз).
    area_union = "".join(
        f'area["{key}"="{safe_city}"]["place"~"city|town"];'
        for key in _CITY_NAME_KEYS
    )
    return (
        f'[out:json][timeout:{REQUEST_TIMEOUT_SECONDS - 10}];'
        f'({area_union})->.a;'
        f'('
        f'node["{tag_key}"="{tag_value}"](area.a);'
        f'way["{tag_key}"="{tag_value}"](area.a);'
        f');'
        f'out center tags {MAX_LIMIT};'
    )


def _build_address(tags: dict) -> str | None:
    parts = []
    street = tags.get("addr:street")
    house = tags.get("addr:housenumber")
    city = tags.get("addr:city")
    if street:
        parts.append(f"{street}{', ' + house if house else ''}" if house else street)
    if city:
        parts.append(city)
    return ", ".join(parts) or None


def parse_elements(data: dict) -> list[Company]:
    """Парсит ответ Overpass. Элементы без названия пропускаем — карточка бесполезна."""
    companies: list[Company] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        companies.append(
            Company(
                name=name,
                address=_build_address(tags),
                phone=tags.get("phone") or tags.get("contact:phone"),
                website=tags.get("website") or tags.get("contact:website"),
            )
        )
        if len(companies) >= MAX_LIMIT:
            break
    return companies


async def _request_overpass(query: str) -> dict:
    from config import settings

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    attempts = max(1, settings.external_retry_attempts + 1)
    for attempt in range(attempts):
        try:
            async with _get_request_semaphore():
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(OVERPASS_URL, data={"data": query}) as resp:
                        if resp.status >= 400:
                            if resp.status < 500 or resp.status == 501:
                                raise PlacesError(f"Overpass HTTP {resp.status}")
                            raise _RetryablePlacesError(resp.status, _retry_after(resp))
                        length = getattr(resp, "content_length", None)
                        if length is not None and length > settings.overpass_max_response_bytes:
                            raise PlacesError("Overpass response too large")
                        content = getattr(resp, "content", None)
                        if content is None:
                            parsed = await resp.json(content_type=None)
                        else:
                            body = await content.read(settings.overpass_max_response_bytes + 1)
                            if len(body) > settings.overpass_max_response_bytes:
                                raise PlacesError("Overpass response too large")
                            parsed = json.loads(body)
                        if not isinstance(parsed, dict):
                            raise ValueError("JSON root is not an object")
                        return parsed
        except _RetryablePlacesError as exc:
            if attempt + 1 >= attempts:
                raise PlacesError(f"Overpass HTTP {exc.status}") from exc
            await asyncio.sleep(
                exc.delay if exc.delay is not None
                else settings.external_retry_base_delay_seconds * (2 ** attempt)
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            if attempt + 1 >= attempts:
                raise PlacesError("Overpass request timed out") from exc
            await asyncio.sleep(settings.external_retry_base_delay_seconds * (2 ** attempt))
        except aiohttp.ClientError as exc:
            if attempt + 1 >= attempts:
                raise PlacesError(f"Overpass network error: {exc}") from exc
            await asyncio.sleep(settings.external_retry_base_delay_seconds * (2 ** attempt))
        except ValueError as exc:
            raise PlacesError(f"Overpass returned invalid JSON: {exc}") from exc
    raise PlacesError("Overpass request failed after retries")


def _retry_after(response) -> float | None:
    value = getattr(response, "headers", {}).get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


async def search_companies(city: str, category_slug: str) -> list[Company]:
    """Поиск компаний с TTL-кэшем результатов (PERF-1).

    Повторный запрос того же города+категории в течение CACHE_TTL_SECONDS
    возвращает кэшированный результат без обращения к Overpass API.
    Бросает PlacesError при любой проблеме с API.
    """
    if category_slug not in CATEGORIES:
        raise PlacesError(f"Unknown category: {category_slug!r}")

    cache_key = f"{normalize_city(city)}:{category_slug}"
    now = time.monotonic()
    if cache_key in _overpass_cache:
        cached_at, cached_result = _overpass_cache[cache_key]
        if now - cached_at < CACHE_TTL_SECONDS:
            _overpass_cache.move_to_end(cache_key)
            logger.debug("Overpass cache hit: city=%r category=%r", city, category_slug)
            return cached_result
        del _overpass_cache[cache_key]

    _, tag_key, tag_value = CATEGORIES[category_slug]
    async with _inflight_lock:
        task = _inflight.get(cache_key)
        if task is None:
            query = build_query(city, tag_key, tag_value)
            task = asyncio.create_task(_request_overpass(query))
            _inflight[cache_key] = task
    try:
        data = await task
    except PlacesError as exc:
        logger.error("Overpass search failed for city=%r category=%r: %s", city, category_slug, exc)
        raise
    finally:
        async with _inflight_lock:
            if _inflight.get(cache_key) is task:
                _inflight.pop(cache_key, None)
    result = parse_elements(data)
    _overpass_cache[cache_key] = (time.monotonic(), result)
    _overpass_cache.move_to_end(cache_key)
    from config import settings

    while len(_overpass_cache) > settings.overpass_cache_max_entries:
        _overpass_cache.popitem(last=False)
    return result
