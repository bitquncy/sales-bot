"""Живой (не моковый) прогон ВСЕХ функций бота через прямой вызов хендлеров.

Аналог scripts/smoke_llm.py, но шире: гоняет весь пользовательский путь
(старт -> меню -> поиск -> карточка -> AI-анализ -> генерация -> CRM ->
напоминания -> настройки) прямыми вызовами реальных хендлеров через
Fake*-объекты, БЕЗ мокания внешних сервисов — реальный Overpass и реальный
LLM из .env. НЕ часть pytest (реальная сеть, отдельный ручной прогон).

Запуск из корня проекта (заполненный .env, активированный venv 3.11):
    python scripts/live_walkthrough.py

Пишет в отдельную временную БД (DB_URL переопределяется ниже), чтобы не
трогать рабочую sales_agent.db.
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Запуск как `python scripts/live_walkthrough.py` из корня проекта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Отдельная временная БД — до импорта config/db.base (engine создаётся при импорте).
_TMP_DB = Path(tempfile.gettempdir()) / "sales_agent_live_walkthrough.db"
_TMP_DB.unlink(missing_ok=True)
os.environ["DB_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"

from config import settings  # noqa: E402
from db import repo  # noqa: E402
from db.base import init_db, session_factory  # noqa: E402
from db.models import STATUS_LABELS, utcnow  # noqa: E402
from handlers import analysis, crm, menu, messages, search, start  # noqa: E402
from handlers.company import format_company_card, format_lead_card  # noqa: E402
from services import reminders as reminders_svc  # noqa: E402
from services.places import PlacesError, search_companies  # noqa: E402
from states.fsm import EditMessageFSM, NoteFSM, ReminderFSM, SearchFSM  # noqa: E402

# Fake-объекты для прямого вызова хендлеров (те же, что в pytest).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from tests.fakes import FakeCallback, FakeMessage, FakeState  # noqa: E402

USER_ID = 777001
findings: list[str] = []  # что нашли (баги/подозрения)


def hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def note_finding(text: str) -> None:
    findings.append(text)
    print(f"  [!!] НАХОДКА: {text}")


def scan_for_none(label: str, text: str) -> None:
    """Ищет буквальный 'None' в отрендеренном тексте (признак утечки пустого поля)."""
    # Отдельные слова вроде 'None' в адресе крайне маловероятны; ищем ' None'
    # как отдельный токен, который появляется при str(None) в f-строке.
    for token in ("None", "null"):
        if token in text.split():
            note_finding(f"{label}: в отрендеренном тексте встречается '{token}': {text!r}")


class FakeBot:
    """Записывает send_message-вызовы (для проверки поллера напоминаний)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))
        return FakeMessage(text=text)


# --------------------------------------------------------------------------- #
#  Шаг 1. Старт и меню
# --------------------------------------------------------------------------- #

async def step1_start_and_menu() -> None:
    hr("ШАГ 1. Старт и меню")

    msg = FakeMessage(text="/start", user_id=USER_ID)
    await start.cmd_start(msg)
    greeting = msg.last_text()
    print("  /start ->", greeting[:80].replace("\n", " "), "…")
    async with session_factory() as s:
        user = await repo.get_or_create_user(s, USER_ID)
    print(f"  Пользователь в БД: id={user.id} tg={user.tg_user_id}")
    if "<tg-emoji" not in greeting:
        note_finding("В приветствии нет кастомных эмодзи (E.*) — проверь emoji_config.")

    # Главное меню: settings
    cb = FakeCallback(data="menu:settings", user_id=USER_ID)
    await menu.show_settings(cb)
    print("  menu:settings ->", cb.message.last_text()[:70].replace("\n", " "), "…")

    # menu:main
    cb = FakeCallback(data="menu:main", user_id=USER_ID)
    st = FakeState()
    await menu.show_main_menu(cb, st)
    print("  menu:main ->", cb.message.last_text()[:70].replace("\n", " "), "…")

    # menu:leads (пустой список на старте)
    cb = FakeCallback(data="menu:leads", user_id=USER_ID)
    await crm.show_leads_menu(cb, FakeState())
    print("  menu:leads ->", cb.message.last_text()[:70].replace("\n", " "), "…")
    print("  Все пункты главного меню открылись без ошибок.")


# --------------------------------------------------------------------------- #
#  Шаг 2. Поиск (реальный Overpass, разные города)
# --------------------------------------------------------------------------- #

# (город, категория-slug) — разный регистр, дефис, два слова, «на-Дону».
SEARCH_CASES = [
    ("астана", "cafe"),            # нижний регистр (уже был баг)
    ("Усть-Каменогорск", "cafe"),  # дефис
    ("Нижний Новгород", "cafe"),   # два слова
    ("Ростов-на-Дону", "cafe"),    # дефис + служебное слово «на» (title() ломает регистр)
    ("Алматы", "restaurant"),      # другая категория
]

# Возвращаем собранные компании для следующих шагов.
async def step2_search() -> dict[str, list[dict]]:
    hr("ШАГ 2. Поиск — реальный Overpass, разные города/категории")
    collected: dict[str, list[dict]] = {}

    for city, cat in SEARCH_CASES:
        # Прямой сервисный вызов — чистый результат Overpass (без FSM-обвязки).
        try:
            companies = await search_companies(city, cat)
        except PlacesError as exc:
            print(f"  {city!r}/{cat}: PlacesError (внешний сервис): {exc}")
            note_finding(
                f"Поиск {city!r}/{cat}: Overpass недоступен/ошибка — {exc} "
                "(вероятно ограничение внешнего сервиса, повтори позже)."
            )
            await asyncio.sleep(3)
            continue
        n = len(companies)
        print(f"  {city!r}/{cat}: {n} компаний")
        collected[f"{city}/{cat}"] = [c.to_dict() for c in companies]
        if n == 0:
            note_finding(
                f"Поиск {city!r}/{cat} вернул 0 — возможно скрытая проблема "
                "нормализации города (как было с «Астаной»), проверь регистр/название в OSM."
            )
        else:
            sample = companies[0]
            print(f"      пример: {sample.name!r} | адрес={sample.address!r} "
                  f"| тел={sample.phone!r} | сайт={sample.website!r}")
        await asyncio.sleep(3)  # вежливо к Overpass, снижаем риск 429

    # Полный FSM-путь для одного города (start_search -> city -> category).
    hr("ШАГ 2b. Полный FSM-путь поиска (город -> категория -> карточки)")
    st = FakeState()
    cb = FakeCallback(data="menu:search", user_id=USER_ID)
    await search.start_search(cb, st)
    print("  start_search: state =", st.state)

    city_msg = FakeMessage(text="Астана", user_id=USER_ID)
    await search.city_received(city_msg, st)
    print("  city_received('Астана'): state =", st.state, "| data.city =", st.data.get("city"))

    cat_cb = FakeCallback(data="cat:cafe", user_id=USER_ID)
    try:
        await search.category_chosen(cat_cb, st)
    except Exception as exc:
        note_finding(f"category_chosen упал: {type(exc).__name__}: {exc}")
        return collected
    results = st.data.get("results") or []
    print(f"  category_chosen('cafe'): state={st.state}, результатов={len(results)}")
    last = cat_cb.message.last_text()
    print("  Ответ:", last[:80].replace("\n", " "), "…")
    if results:
        collected["_fsm_astana_cafe"] = results
    return collected


# --------------------------------------------------------------------------- #
#  Шаг 3. Карточка компании (в т.ч. с отсутствующими полями)
# --------------------------------------------------------------------------- #

async def step3_company_cards(pool: dict[str, list[dict]]) -> None:
    hr("ШАГ 3. Карточки компаний (реальные результаты, в т.ч. без полей)")
    all_companies = [c for lst in pool.values() for c in lst]
    if not all_companies:
        note_finding("Нет результатов поиска для проверки карточек (шаг 3 пропущен).")
        return

    no_site = [c for c in all_companies if not c.get("website")]
    no_phone = [c for c in all_companies if not c.get("phone")]
    with_site = [c for c in all_companies if c.get("website")]
    special = [c for c in all_companies
               if any(ch in c["name"] for ch in ('&', '<', '>', '"', '«', '»', "'"))]

    samples = []
    if no_site:
        samples.append(("без сайта", no_site[0]))
    if no_phone:
        samples.append(("без телефона", no_phone[0]))
    if with_site:
        samples.append(("с сайтом", with_site[0]))
    if special:
        samples.append(("спецсимволы в названии", special[0]))

    for label, company in samples:
        card = format_company_card(company)
        print(f"\n  [{label}] {company['name']!r}")
        print("   ", card.replace("\n", "\n    "))
        scan_for_none(f"карточка ({label})", card)

    # Пагинация через FSM (проверяем _show_card на индексах).
    fsm_results = pool.get("_fsm_astana_cafe") or all_companies
    st = FakeState(data={"results": fsm_results, "saved_leads": {}}, state=SearchFSM.browsing)
    for idx in (0, min(1, len(fsm_results) - 1), len(fsm_results) - 1):
        cb = FakeCallback(data=f"spg:{idx}", user_id=USER_ID)
        await search.paginate(cb, st)
        txt = cb.message.last_text()
        scan_for_none(f"пагинация idx={idx}", txt)
    print(f"\n  Пагинация по {len(fsm_results)} карточкам — без 'None'/краха.")


# --------------------------------------------------------------------------- #
#  Шаг 4. AI-анализ (реальный LLM, 3 разные компании)
# --------------------------------------------------------------------------- #

async def _make_lead(name, address=None, phone=None, website=None) -> int:
    async with session_factory() as s:
        lead = await repo.create_lead(
            s, owner_tg_id=USER_ID, name=name, address=address, phone=phone, website=website
        )
        return lead.id


async def step4_ai_analysis(pool: dict[str, list[dict]]) -> list[int]:
    hr("ШАГ 4. AI-анализ — реальный LLM, 3 разные компании")
    all_companies = [c for lst in pool.values() for c in lst]

    # 1) реальная компания без сайта
    without_site = next((c for c in all_companies if not c.get("website")), None)
    # 2) реальная компания с сайтом
    with_site = next((c for c in all_companies if c.get("website")), None)

    cases: list[tuple[str, dict]] = []
    if without_site:
        cases.append(("без сайта (реальная)", without_site))
    if with_site:
        cases.append(("с сайтом (реальная)", with_site))
    else:
        note_finding("Среди реальных результатов Overpass не нашлось компании с website "
                     "(OSM редко отдаёт сайт) — кейс «с сайтом» подставлен синтетически.")
        cases.append(("с сайтом (синтетическая)", {
            "name": "Стоматология «Улыбка+»",
            "address": "пр. Достык, 5, Алматы",
            "phone": "+7 727 000-00-00",
            "website": "https://ulybka.example.kz",
        }))
    # 3) необычное название со спецсимволами (& < > " и эмодзи)
    cases.append(("спецсимволы+эмодзи в названии", {
        "name": 'Кафе «Бар & Гриль» <M&M> "У Ко\'ста" 🍔',
        "address": "ул. Пушкина, д. 1 <корпус A>",
        "phone": None,
        "website": None,
    }))

    lead_ids: list[int] = []
    for label, company in cases[:3]:
        print(f"\n  [{label}] {company['name']!r} (сайт={company.get('website')!r})")
        lead_id = await _make_lead(
            company["name"], company.get("address"), company.get("phone"), company.get("website")
        )
        # Прямой вызов хендлера анализа из карточки лида (реальный LLM внутри).
        cb = FakeCallback(data=f"anl:{lead_id}", user_id=USER_ID)
        try:
            await analysis.analyze_from_lead(cb)
        except Exception as exc:
            note_finding(f"analyze_from_lead УПАЛ на {label}: {type(exc).__name__}: {exc}")
            continue
        async with session_factory() as s:
            lead = await repo.get_lead(s, lead_id, USER_ID)
        card_text = cb.message.last_text()
        if lead.ai_analysis:
            print(f"      score={lead.ai_score} online_booking={lead.has_online_booking}")
            print("      анализ:", lead.ai_analysis[:120].replace("\n", " "), "…")
            lead_ids.append(lead_id)
        else:
            # Хендлер не упал, но анализ не сохранён — модель вернула не-формат.
            print("      анализ НЕ сохранён; ответ хендлера:",
                  card_text[:100].replace("\n", " "))
            note_finding(
                f"AI-анализ ({label}): результат не сохранён — модель вернула не по формату. "
                "Хендлер не упал (ОК), но кейс стоит отметить."
            )
        scan_for_none(f"карточка лида после анализа ({label})", card_text)
        await asyncio.sleep(1)
    return lead_ids


# --------------------------------------------------------------------------- #
#  Шаг 5. Генерация сообщений + редактирование
# --------------------------------------------------------------------------- #

async def step5_messages(analyzed_lead_ids: list[int]) -> None:
    hr("ШАГ 5. Генерация сообщений + редактирование (реальный LLM)")
    if not analyzed_lead_ids:
        note_finding("Нет проанализированных лидов — шаг 5 пропущен.")
        return
    lead_id = analyzed_lead_ids[-1]  # берём лид со спецсимволами в названии, если есть
    async with session_factory() as s:
        lead = await repo.get_lead(s, lead_id, USER_ID)
    print(f"  Генерация для лида #{lead_id} {lead.name!r}")

    st = FakeState()
    cb = FakeCallback(data=f"gen:{lead_id}", user_id=USER_ID)
    try:
        await messages.generate_for_lead(cb, st)
    except Exception as exc:
        note_finding(f"generate_for_lead УПАЛ: {type(exc).__name__}: {exc}")
        return
    rendered = cb.message.last_text()
    if "gen_short" not in st.data:
        note_finding("После генерации в state нет gen_short/gen_long — генерация не удалась. "
                     f"Ответ: {rendered[:120]!r}")
        return
    print("  Сгенерировано. HTML-рендер (первые строки):")
    print("   ", rendered[:200].replace("\n", "\n    "))
    # Проверяем экранирование спецсимволов в HTML.
    if "<b>" not in rendered:
        note_finding("В отрендеренных сообщениях нет <b> — проверь HTML-разметку.")
    if "&amp;" not in rendered and "&" in lead.name:
        note_finding("Название содержит '&', но в HTML нет '&amp;' — возможна проблема экранирования.")

    # Редактирование короткого варианта.
    cb_edit = FakeCallback(data=f"edm:{lead_id}:short", user_id=USER_ID)
    await messages.edit_message_start(cb_edit, st)
    print("  edit_message_start(short): state =", st.state)
    new_text = 'Отредактировано вручную: спецсимволы & < > " и эмодзи 🚀'
    edit_msg = FakeMessage(text=new_text, user_id=USER_ID)
    await messages.edit_message_received(edit_msg, st)
    edited = edit_msg.last_text()
    print("  После редактирования (HTML):")
    print("   ", edited[:220].replace("\n", "\n    "))
    if "&amp;" not in edited or "&lt;" not in edited or "&gt;" not in edited:
        note_finding("Отредактированный текст со спецсимволами не экранирован в HTML "
                     f"(ожидались &amp; &lt; &gt;): {edited!r}")
    else:
        print("  Спецсимволы корректно экранированы (&amp; &lt; &gt;).")


# --------------------------------------------------------------------------- #
#  Шаг 6. CRM: лиды, статусы, заметки, фильтры
# --------------------------------------------------------------------------- #

async def step6_crm(pool: dict[str, list[dict]]) -> list[int]:
    hr("ШАГ 6. CRM — сохранение, статусы, заметки, фильтры")
    fsm_results = pool.get("_fsm_astana_cafe") or next(iter(pool.values()), [])
    if not fsm_results:
        note_finding("Нет результатов для CRM-шага.")
        return []

    # Сохраняем несколько лидов из результатов поиска (реальный save_from_search).
    st = FakeState(data={"results": fsm_results, "saved_leads": {}}, state=SearchFSM.browsing)
    saved_ids: list[int] = []
    for idx in range(min(3, len(fsm_results))):
        cb = FakeCallback(data=f"ssv:{idx}", user_id=USER_ID)
        await search.save_from_search(cb, st)
    async with session_factory() as s:
        leads = await repo.list_leads(s, USER_ID)
    saved_ids = [l.id for l in leads]
    print(f"  Сохранено лидов всего в БД: {len(leads)}")

    # Меняем статусы.
    target = saved_ids[0]
    for status in ("written", "replied", "client"):
        cb = FakeCallback(data=f"sts:{target}:{status}", user_id=USER_ID)
        await crm.change_status(cb)
    async with session_factory() as s:
        lead = await repo.get_lead(s, target, USER_ID)
    print(f"  Лид #{target}: статус -> {lead.status} ({STATUS_LABELS[lead.status]})")
    if lead.status != "client":
        note_finding(f"Статус лида #{target} ожидался 'client', получен {lead.status!r}.")

    # Невалидный статус (симуляция битого callback).
    cb = FakeCallback(data=f"sts:{target}:bogus", user_id=USER_ID)
    await crm.change_status(cb)
    if not cb.alert_texts():
        note_finding("Невалидный статус не дал show_alert-предупреждения.")
    else:
        print("  Невалидный статус -> alert:", cb.alert_texts()[0])

    # Заметка.
    cb = FakeCallback(data=f"note:{target}", user_id=USER_ID)
    st_note = FakeState()
    await crm.note_start(cb, st_note)
    note_msg = FakeMessage(text="Позвонить после обеда. Спецсимволы & <тест>", user_id=USER_ID)
    await crm.note_received(note_msg, st_note)
    async with session_factory() as s:
        lead = await repo.get_lead(s, target, USER_ID)
    print(f"  Заметка сохранена: {lead.note!r}")
    card = format_lead_card(lead)
    scan_for_none("карточка лида (CRM)", card)
    if lead.note and "&amp;" not in card:
        note_finding("Заметка со спецсимволом '&' не экранирована в карточке лида.")

    # Фильтры: все, по статусу с результатом, по статусу пустой, no_booking.
    for filt, expect_desc in [
        ("all", "все"),
        ("client", "есть client"),
        ("rejected", "пусто (нет rejected)"),
        ("no_booking", "без онлайн-записи"),
    ]:
        cb = FakeCallback(data=f"leads:{filt}", user_id=USER_ID)
        await crm.list_leads_filtered(cb)
        txt = cb.message.last_text()
        print(f"  Фильтр leads:{filt} [{expect_desc}] -> {txt[:70].replace(chr(10), ' ')!r}")
    return saved_ids


# --------------------------------------------------------------------------- #
#  Шаг 7. Напоминания — живой поллер, близкое время, без задвоения
# --------------------------------------------------------------------------- #

async def step7_reminders(saved_ids: list[int]) -> None:
    hr("ШАГ 7. Напоминания — живой поллер (близкое время, дедуп)")
    if not saved_ids:
        note_finding("Нет лидов для напоминаний.")
        return
    lead_id = saved_ids[0]
    bot = FakeBot()

    # (a) Реальный хендлер кастомной даты: ставим на ближайшую минуту (UTC).
    st = FakeState()
    cb = FakeCallback(data=f"remc:{lead_id}", user_id=USER_ID)
    await crm.reminder_custom_start(cb, st)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target = (now + timedelta(seconds=70)).replace(second=0, microsecond=0)
    date_str = target.strftime("%d.%m.%Y %H:%M")
    dmsg = FakeMessage(text=date_str, user_id=USER_ID)
    await crm.reminder_custom_received(dmsg, st)
    print(f"  Хендлер remc: поставлено на {date_str} UTC (через ~{(target-now).seconds}s)")
    print("   ответ:", dmsg.last_text()[:80].replace("\n", " "))

    # (b) Быстрый лид напрямую через repo — due через ~4с (для проверки дедупа поллера).
    async with session_factory() as s:
        fast_due = utcnow() + timedelta(seconds=4)
        await repo.create_reminder(s, lead_id, USER_ID, fast_due, text="Быстрое тест-напоминание")
    print("  Вставлено быстрое напоминание (due ~4s) через repo.")

    # Запускаем ЖИВОЙ поллер (тот же reminders_loop) с коротким интервалом.
    loop_task = asyncio.create_task(
        reminders_svc.reminders_loop(bot, session_factory, interval_seconds=3)
    )
    try:
        # Ждём срабатывания обоих напоминаний (быстрого ~4с и ближайшей минуты).
        deadline = 150
        waited = 0
        while waited < deadline and len(bot.sent) < 2:
            await asyncio.sleep(3)
            waited += 3
        print(f"  За {waited}s поллер отправил {len(bot.sent)} уведомлений.")
        for chat_id, text in bot.sent:
            print(f"   -> chat={chat_id}: {text[:90].replace(chr(10), ' ')!r}")

        # Проверяем текст уведомления.
        if not bot.sent:
            note_finding("Живой поллер не отправил ни одного напоминания за отведённое время.")
        else:
            first = bot.sent[0][1]
            if "Напоминание по лиду" not in first:
                note_finding(f"Текст напоминания неожиданный: {first!r}")

        # Дедуп: считаем текущее число и ждём ещё интервал — не должно вырасти.
        count_before = len(bot.sent)
        await asyncio.sleep(7)
        count_after = len(bot.sent)
        if count_after != count_before:
            note_finding(
                f"ЗАДВОЕНИЕ напоминаний: было {count_before}, стало {count_after} "
                "после дополнительного прохода поллера."
            )
        else:
            print(f"  Дедуп OK: после ещё одного прохода по-прежнему {count_after} уведомлений.")
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass


# --------------------------------------------------------------------------- #
#  Шаг 8. Настройки
# --------------------------------------------------------------------------- #

async def step8_settings() -> None:
    hr("ШАГ 8. Настройки")
    cb = FakeCallback(data="menu:settings", user_id=USER_ID)
    await menu.show_settings(cb)
    print("  menu:settings ->", cb.message.last_text().replace("\n", " "))
    print("  (Настройки — заглушка: токены в .env, отдельных пунктов нет.)")


# --------------------------------------------------------------------------- #

async def main() -> int:
    print(f"[live] provider={settings.llm_provider!r} model={settings.llm_model!r}")
    print(f"[live] БД: {os.environ['DB_URL']}")
    if not settings.llm_ready:
        print("[live] LLM не сконфигурирован — шаги 4-5 не пройдут.", file=sys.stderr)
    await init_db()

    await step1_start_and_menu()
    pool = await step2_search()
    await step3_company_cards(pool)
    analyzed = await step4_ai_analysis(pool)
    await step5_messages(analyzed)
    saved_ids = await step6_crm(pool)
    await step7_reminders(saved_ids)
    await step8_settings()

    hr("ИТОГ")
    if findings:
        print(f"Находок/подозрений: {len(findings)}")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
    else:
        print("Находок нет — весь путь прошёл чисто.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
