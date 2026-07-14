"""Клиент OpenStreetMap Overpass API — поиск компаний по городу и категории.

Бесплатно, без ключей. Лимит результатов MAX_LIMIT — без него Overpass
может вернуть тысячи строк и повесить бота.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_LIMIT = 60
REQUEST_TIMEOUT_SECONDS = 40

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
    """Убирает символы, ломающие Overpass QL: кавычки, бэкслеш, [ ] ~.

    Значение подставляется внутрь "..." в QL. Эти символы либо закрывают
    строку/фильтр раньше времени (инъекция), либо просто дают синтаксически
    битый запрос -> PlacesError там, где мог бы быть нормальный результат.
    """
    for ch in ('\\', '"', "[", "]", "~"):
        value = value.replace(ch, "")
    return value


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
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OVERPASS_URL, data={"data": query}) as resp:
                if resp.status >= 400:
                    raise PlacesError(f"Overpass HTTP {resp.status}")
                try:
                    return await resp.json(content_type=None)
                except Exception as exc:
                    raise PlacesError(f"Overpass returned invalid JSON: {exc}") from exc
    except PlacesError:
        raise
    except (asyncio.TimeoutError, TimeoutError) as exc:
        # aiohttp по total-таймауту бросает asyncio.TimeoutError. На Python 3.10
        # это отдельный класс (не подкласс встроенного TimeoutError), поэтому
        # ловим оба явно — работает и на 3.10, и на 3.11+ (где это алиас).
        raise PlacesError("Overpass request timed out") from exc
    except aiohttp.ClientError as exc:
        raise PlacesError(f"Overpass network error: {exc}") from exc


async def search_companies(city: str, category_slug: str) -> list[Company]:
    """Поиск компаний. Бросает PlacesError при любой проблеме с API."""
    if category_slug not in CATEGORIES:
        raise PlacesError(f"Unknown category: {category_slug!r}")
    _, tag_key, tag_value = CATEGORIES[category_slug]
    query = build_query(city, tag_key, tag_value)
    try:
        data = await _request_overpass(query)
    except PlacesError as exc:
        logger.error("Overpass search failed for city=%r category=%r: %s", city, category_slug, exc)
        raise
    return parse_elements(data)
