"""Production hardening: distributed quotas/claims, crypto and config gates."""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from config import Settings
from db import repo
from db.base import verify_schema
from db.models import utcnow


async def test_llm_budget_isolated_per_owner(session):
    assert (await repo.check_llm_budget(session, 1, 101, "analysis"))[0] is True
    assert (await repo.check_llm_budget(session, 1, 101, "analysis"))[0] is False
    assert (await repo.check_llm_budget(session, 1, 202, "analysis"))[0] is True


async def test_chat_message_claim_is_atomic(session):
    args = (session, 1, "chat", 2, 3)
    assert await repo.claim_chat_message(*args) is True
    assert await repo.claim_chat_message(*args) is False
    await repo.release_chat_message_claim(*args)
    assert await repo.claim_chat_message(*args) is True


async def test_claim_due_reminders_is_bounded(session_factory):
    async with session_factory() as session:
        lead = await repo.create_lead(session, 1, "Reminder Co")
        for i in range(3):
            await repo.create_reminder(
                session, lead.id, 1, utcnow() - timedelta(minutes=i + 1), str(i)
            )
    async with session_factory() as session:
        first = await repo.claim_due_reminders(session, limit=2)
    async with session_factory() as session:
        second = await repo.claim_due_reminders(session, limit=2)
    assert len(first) == 2
    assert len(second) == 1


async def test_verify_schema_rejects_empty_db(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    try:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            await verify_schema(engine)
    finally:
        await engine.dispose()


def test_production_config_can_be_valid(tmp_path):
    pii_key = Fernet.generate_key().decode()
    backup_key = Fernet.generate_key().decode()
    settings = Settings(
        _env_file=None,
        environment="production",
        secrets_rotated_at="2026-07-20T16:00:00Z",
        bot_token="123456:rotated-token",
        llm_provider="openrouter",
        llm_model="model",
        llm_api_key="rotated-llm-key",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_daily_limit=100,
        db_url="postgresql+asyncpg://u:p@db:5432/app",
        auto_create_schema=False,
        redis_url="redis://:password@redis:6379/0",
        allowed_user_ids="123",
        pii_encryption_key=pii_key,
        backup_encryption_key=backup_key,
        backup_dir=str(tmp_path / "backups"),
    )
    from utils.config_validator import validate_config

    assert validate_config(settings) == []


def test_chat_refs_are_bounded_and_strict():
    from chat_monitor.config_store import parse_chat_refs

    assert parse_chat_refs("@ok_user, @x, @bad-name, -100123") == ["@ok_user", "-100123"]
    values = ",".join(f"@chat_{i}" for i in range(10))
    assert len(parse_chat_refs(values, max_refs=3)) == 3


async def test_redis_lock_release_checks_owner(monkeypatch):
    from utils import idempotency

    class FakeRedis:
        def __init__(self):
            self.values = {}

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

        async def eval(self, script, keys, key, token):
            if self.values.get(key) == token:
                del self.values[key]
                return 1
            return 0

    redis = FakeRedis()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(idempotency.redis_client, "get_redis", fake_get_redis)
    token = await idempotency.acquire_lock("resource", ttl=10)
    assert token
    await idempotency.release_lock("resource", "wrong-owner")
    assert "lock:resource" in redis.values
    await idempotency.release_lock("resource", token)
    assert "lock:resource" not in redis.values
