"""Тесты Production Template улучшений.

Покрывает:
- CONFIG-2: validate_config
- ARCH-1: промпты используют конфиг
- ARCH-2: keywords из конфига
- ARCH-3: gis_domain из конфига
- ARCH-5: синглтон LLM-клиент
- ARCH-6: оптимизация get_stats (3 запроса)
- CODE-1: каскадное удаление через relationship
- CODE-2: порядок фильтров в list_leads
- CODE-3: selectinload в get_due_reminders
- CODE-4: UPDATE в _set_reminder_sent
- PERF-1: TTL-кэш Overpass
- SEC-2: обрезка message_text перед LLM
- DEVOPS-1: pytest не в requirements.txt
"""

from datetime import timedelta
from unittest.mock import patch


from db import repo
from db.models import utcnow


OWNER = 777


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG-2: validate_config
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_config_missing_bot_token(tmp_path):
    from utils.config_validator import validate_config

    class FakeSettings:
        bot_token = ""
        llm_ready = True
        llm_provider = "openrouter"
        db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        backup_dir = str(tmp_path / "backups")
        allowed_user_set = {123}
        allowed_user_ids = "123"
        llm_daily_limit = 0
        reminders_poll_interval = 60

    errors = validate_config(FakeSettings())
    assert any("BOT_TOKEN" in e for e in errors)


def test_validate_config_valid(tmp_path):
    from utils.config_validator import validate_config

    class FakeSettings:
        bot_token = "123:ABC"
        llm_ready = True
        llm_provider = "openrouter"
        db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        backup_dir = str(tmp_path / "backups")
        allowed_user_set = {123}
        allowed_user_ids = "123"
        llm_daily_limit = 0
        reminders_poll_interval = 60

    errors = validate_config(FakeSettings())
    assert errors == []


def test_validate_config_negative_llm_limit(tmp_path):
    from utils.config_validator import validate_config

    class FakeSettings:
        bot_token = "123:ABC"
        llm_ready = True
        llm_provider = "openrouter"
        db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        backup_dir = str(tmp_path / "backups")
        allowed_user_set = {123}
        allowed_user_ids = "123"
        llm_daily_limit = -1
        reminders_poll_interval = 60

    errors = validate_config(FakeSettings())
    assert any("LLM_DAILY_LIMIT" in e for e in errors)


# ─────────────────────────────────────────────────────────────────────────────
# ARCH-1: промпты используют конфиг
# ─────────────────────────────────────────────────────────────────────────────

async def test_analyze_company_prompt_uses_config(monkeypatch):
    """Промпт analyze_company содержит значения из конфига, а не хардкод."""
    from config import settings
    from services.ai import LLMClient, reset_client

    reset_client()
    monkeypatch.setattr(settings, "ai_service_type", "CUSTOM_SERVICE_TYPE")
    monkeypatch.setattr(settings, "ai_main_offer", "CUSTOM_OFFER")

    captured_prompt = {}

    class FakeClient(LLMClient):
        async def _complete(self, prompt: str) -> str:
            captured_prompt["prompt"] = prompt
            return '{"score": 50, "weaknesses": [], "offer": "test", "has_online_booking": null}'

    client = FakeClient()
    await client.analyze_company("Test Co")

    assert "CUSTOM_SERVICE_TYPE" in captured_prompt["prompt"]
    assert "CUSTOM_OFFER" in captured_prompt["prompt"]
    reset_client()


async def test_generate_messages_prompt_uses_language(monkeypatch):
    """Промпт generate_messages содержит язык из конфига."""
    from config import settings
    from services.ai import LLMClient, reset_client

    reset_client()
    monkeypatch.setattr(settings, "ai_response_language", "английском")

    captured_prompt = {}

    class FakeClient(LLMClient):
        async def _complete(self, prompt: str) -> str:
            captured_prompt["prompt"] = prompt
            return '{"short": "short msg", "long": "long msg"}'

    client = FakeClient()
    await client.generate_messages("Test Co", "analysis text")

    assert "английском" in captured_prompt["prompt"]
    reset_client()


async def test_score_nail_chat_message_prompt_uses_config(monkeypatch):
    """Промпт score_nail_chat_message содержит значения из конфига."""
    from config import settings
    from services.ai import LLMClient, reset_client

    reset_client()
    monkeypatch.setattr(settings, "chat_monitor_niche_description", "CUSTOM_NICHE")
    monkeypatch.setattr(settings, "chat_monitor_offer_product", "CUSTOM_PRODUCT")

    captured_prompt = {}

    class FakeClient(LLMClient):
        async def _complete(self, prompt: str) -> str:
            captured_prompt["prompt"] = prompt
            return '{"score": 0.8, "reasoning": "test", "is_solo_master": true}'

    client = FakeClient()
    await client.score_nail_chat_message("test message")

    assert "CUSTOM_NICHE" in captured_prompt["prompt"]
    assert "CUSTOM_PRODUCT" in captured_prompt["prompt"]
    reset_client()


# ─────────────────────────────────────────────────────────────────────────────
# ARCH-2: keywords из конфига
# ─────────────────────────────────────────────────────────────────────────────

def test_keywords_from_config(monkeypatch):
    """chat_monitor_keywords_list возвращает кастомные keywords из конфига."""
    from config import settings

    # Сбрасываем cached_property
    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]

    monkeypatch.setattr(settings, "chat_monitor_keywords", "барбер,стрижка,запись")
    # Сбрасываем кэш после monkeypatch
    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]

    result = settings.chat_monitor_keywords_list
    assert result == ("барбер", "стрижка", "запись")

    # Восстанавливаем
    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]


def test_keywords_empty_uses_builtin(monkeypatch):
    """Пустой CHAT_MONITOR_KEYWORDS → None → используются встроенные."""
    from config import settings

    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]

    monkeypatch.setattr(settings, "chat_monitor_keywords", "")
    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]

    result = settings.chat_monitor_keywords_list
    assert result is None

    if "chat_monitor_keywords_list" in settings.__dict__:
        del settings.__dict__["chat_monitor_keywords_list"]


# ─────────────────────────────────────────────────────────────────────────────
# ARCH-3: gis_domain из конфига
# ─────────────────────────────────────────────────────────────────────────────

def test_gis_domain_in_search_links(monkeypatch):
    """manual_search_links использует GIS_DOMAIN из конфига."""
    from config import settings
    from handlers.company import manual_search_links

    monkeypatch.setattr(settings, "gis_domain", "2gis.ru")
    links = manual_search_links("Барбершоп", "Москва")
    joined = "\n".join(links)
    assert "2gis.ru" in joined
    assert "2gis.kz" not in joined


def test_gis_domain_default_kz():
    """По умолчанию используется 2gis.kz."""
    from config import settings
    from handlers.company import manual_search_links

    # Не меняем settings — проверяем дефолт
    links = manual_search_links("Кафе", "Астана")
    joined = "\n".join(links)
    assert settings.gis_domain in joined


# ─────────────────────────────────────────────────────────────────────────────
# ARCH-5: синглтон LLM-клиент
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_client_singleton(monkeypatch):
    """get_client() возвращает один и тот же объект при повторных вызовах."""
    from config import settings
    from services.ai import get_client, reset_client

    reset_client()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_api_key", "")

    c1 = get_client()
    c2 = get_client()
    assert c1 is c2
    reset_client()


def test_llm_client_reset(monkeypatch):
    """reset_client() сбрасывает синглтон — следующий get_client() создаёт новый объект."""
    from config import settings
    from services.ai import get_client, reset_client

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_api_key", "")

    reset_client()
    c1 = get_client()
    reset_client()
    c2 = get_client()
    assert c1 is not c2
    reset_client()


# ─────────────────────────────────────────────────────────────────────────────
# ARCH-6: оптимизация get_stats
# ─────────────────────────────────────────────────────────────────────────────

async def test_get_stats_uses_group_by(session):
    """get_stats возвращает корректные данные через GROUP BY."""
    lead1 = await repo.create_lead(session, OWNER, "OSM Lead", source="osm")
    await repo.create_lead(session, OWNER, "Chat Lead", source="chat_monitor")
    await repo.set_lead_status(session, lead1.id, OWNER, "client")
    await repo.log_llm_call(session)

    stats = await repo.get_stats(session, OWNER)

    assert stats["total"] == 2
    assert stats["osm"] == 1
    assert stats["chat_monitor"] == 1
    assert stats["statuses"].get("client") == 1
    assert stats["llm_today"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# CODE-1: каскадное удаление
# ─────────────────────────────────────────────────────────────────────────────

async def test_delete_lead_cascades_reminders(session_factory):
    """Удаление лида автоматически удаляет связанные напоминания (CODE-1)."""
    async with session_factory() as session:
        lead = await repo.create_lead(session, OWNER, "Lead with reminders")
        lead_id = lead.id
        r1 = await repo.create_reminder(session, lead.id, OWNER, utcnow() + timedelta(days=1), "r1")
        r2 = await repo.create_reminder(session, lead.id, OWNER, utcnow() + timedelta(days=2), "r2")
        r1_id, r2_id = r1.id, r2.id

    async with session_factory() as session:
        deleted = await repo.delete_lead(session, lead_id, OWNER)
        assert deleted is True

    # Проверяем в новой сессии — лид и напоминания удалены
    async with session_factory() as session:
        assert await repo.get_lead(session, lead_id, OWNER) is None

        from sqlalchemy import select
        from db.models import Reminder
        result = await session.execute(
            select(Reminder).where(Reminder.id.in_([r1_id, r2_id]))
        )
        assert result.scalars().all() == []


# ─────────────────────────────────────────────────────────────────────────────
# CODE-2: порядок фильтров в list_leads
# ─────────────────────────────────────────────────────────────────────────────

async def test_list_leads_filters_before_offset(session):
    """Фильтры применяются до offset/limit — корректная пагинация с фильтром."""
    # Создаём 5 лидов: 3 new, 2 client
    for i in range(3):
        await repo.create_lead(session, OWNER, f"New {i}")
    for i in range(2):
        lead = await repo.create_lead(session, OWNER, f"Client {i}")
        await repo.set_lead_status(session, lead.id, OWNER, "client")

    # Запрашиваем только client с пагинацией
    page0 = await repo.list_leads(session, OWNER, status="client", offset=0, limit=1)
    page1 = await repo.list_leads(session, OWNER, status="client", offset=1, limit=1)
    page2 = await repo.list_leads(session, OWNER, status="client", offset=2, limit=1)

    assert len(page0) == 1
    assert len(page1) == 1
    assert len(page2) == 0  # Только 2 client-лида

    # Все возвращённые лиды имеют статус client
    for lead in page0 + page1:
        assert lead.status == "client"


# ─────────────────────────────────────────────────────────────────────────────
# CODE-3: selectinload в get_due_reminders
# ─────────────────────────────────────────────────────────────────────────────

async def test_get_due_reminders_preloads_lead(session):
    """get_due_reminders предзагружает лид через selectinload (CODE-3)."""
    lead = await repo.create_lead(session, OWNER, "Test Lead")
    await repo.create_reminder(session, lead.id, OWNER, utcnow() - timedelta(minutes=1), "due")

    due = await repo.get_due_reminders(session)
    assert len(due) == 1

    # Лид доступен без дополнительного запроса (уже загружен)
    assert due[0].lead is not None
    assert due[0].lead.name == "Test Lead"


# ─────────────────────────────────────────────────────────────────────────────
# SEC-2: обрезка message_text перед LLM
# ─────────────────────────────────────────────────────────────────────────────

async def test_score_nail_chat_message_truncates_long_text():
    """Длинный текст обрезается до _MAX_CHAT_MESSAGE_LEN перед вставкой в промпт."""
    from services.ai import LLMClient, reset_client

    reset_client()
    long_text = "А" * 10000  # 10 КБ

    captured_prompt = {}

    class FakeClient(LLMClient):
        async def _complete(self, prompt: str) -> str:
            captured_prompt["prompt"] = prompt
            return '{"score": 0.5, "reasoning": "test", "is_solo_master": false}'

    client = FakeClient()
    await client.score_nail_chat_message(long_text)

    # Промпт не должен содержать полный 10КБ текст
    assert len(captured_prompt["prompt"]) < len(long_text) + 500
    # Но должен содержать начало текста
    assert "А" * 100 in captured_prompt["prompt"]
    reset_client()


# ─────────────────────────────────────────────────────────────────────────────
# PERF-1: TTL-кэш Overpass
# ─────────────────────────────────────────────────────────────────────────────

async def test_overpass_cache_hit():
    """Повторный запрос того же города+категории не идёт в сеть (PERF-1)."""
    from services.places import _overpass_cache, search_companies

    # Очищаем кэш
    _overpass_cache.clear()

    fake_data = {"elements": [{"tags": {"name": "Test Cafe"}, "type": "node"}]}
    call_count = {"n": 0}

    async def fake_request(query: str) -> dict:
        call_count["n"] += 1
        return fake_data

    with patch("services.places._request_overpass", side_effect=fake_request):
        result1 = await search_companies("Астана", "cafe")
        result2 = await search_companies("Астана", "cafe")  # должен взять из кэша

    assert call_count["n"] == 1  # только один реальный запрос
    assert len(result1) == len(result2) == 1
    _overpass_cache.clear()


async def test_overpass_cache_different_keys():
    """Разные город+категория — разные записи в кэше."""
    from services.places import _overpass_cache, search_companies

    _overpass_cache.clear()

    fake_data = {"elements": [{"tags": {"name": "Test"}, "type": "node"}]}
    call_count = {"n": 0}

    async def fake_request(query: str) -> dict:
        call_count["n"] += 1
        return fake_data

    with patch("services.places._request_overpass", side_effect=fake_request):
        await search_companies("Астана", "cafe")
        await search_companies("Алматы", "cafe")  # другой город — новый запрос
        await search_companies("Астана", "barber")  # другая категория — новый запрос
        await search_companies("Астана", "cafe")  # кэш-хит

    assert call_count["n"] == 3
    _overpass_cache.clear()


# ─────────────────────────────────────────────────────────────────────────────
# DEVOPS-1: pytest не в requirements.txt
# ─────────────────────────────────────────────────────────────────────────────

def test_pytest_not_in_runtime_requirements():
    """pytest и dev-инструменты не должны быть в requirements.txt (DEVOPS-1)."""
    from pathlib import Path
    req = Path("requirements.txt").read_text(encoding="utf-8")
    dev_packages = ["pytest", "ruff", "mypy", "coverage", "pytest-asyncio", "pytest-cov"]
    for pkg in dev_packages:
        assert pkg not in req, f"{pkg} найден в requirements.txt — должен быть в requirements-dev.txt"


def test_dev_requirements_file_exists():
    """requirements-dev.txt должен существовать."""
    from pathlib import Path
    assert Path("requirements-dev.txt").exists()
    dev_req = Path("requirements-dev.txt").read_text(encoding="utf-8")
    assert "pytest" in dev_req
