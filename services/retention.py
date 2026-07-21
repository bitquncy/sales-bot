"""SEC-FIX-4: Retention — автоматическая очистка устаревших ПДн и журналов.

152-ФЗ / GDPR: данные не должны храниться дольше, чем нужно для цели обработки.
Фоновый цикл периодически удаляет/обезличивает:

- llm_call_log     — нужен только для подсчёта дневного лимита → чистим > N дней;
- audit_log        — журнал действий для расследования инцидентов → > N дней;
- leads.message_text — текст чужого сообщения из чата (самое чувствительное):
  лид (контакт, скор) остаётся в CRM, а сам текст обезличивается → NULL;
- soft-deleted лиды — после retention_deleted_lead_days удаляются окончательно
  (hard delete, каскадно с напоминаниями).

Все сроки настраиваются в config (retention_*). Каждый проход — в своей сессии,
сбой одной очистки не мешает остальным и не роняет цикл.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from db.models import AuditLog, ChatMessageInbox, LLMCallLog, Lead, utcnow
from utils.sentry import capture_exception

logger = logging.getLogger(__name__)


async def purge_old_llm_calls(session: AsyncSession, days: int) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = await session.execute(delete(LLMCallLog).where(LLMCallLog.created_at < cutoff))
    await session.commit()
    return result.rowcount or 0


async def purge_old_audit_log(session: AsyncSession, days: int) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await session.commit()
    return result.rowcount or 0


async def purge_old_chat_message_text(session: AsyncSession, days: int) -> int:
    """Обезличивает старые chat-лиды: удаляет текст сообщения, оставляя лид."""
    cutoff = utcnow() - timedelta(days=days)
    result = await session.execute(
        update(Lead)
        .where(
            Lead.source == "chat_monitor",
            Lead.message_text.is_not(None),
            Lead.message_date.is_not(None),
            Lead.message_date < cutoff,
        )
        .values(message_text=None)
    )
    await session.commit()
    return result.rowcount or 0


async def purge_deleted_leads(session: AsyncSession, days: int) -> int:
    """Окончательно удаляет soft-deleted лиды старше N дней (с напоминаниями)."""
    cutoff = utcnow() - timedelta(days=days)
    result = await session.execute(
        delete(Lead).where(Lead.deleted_at.is_not(None), Lead.deleted_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def purge_old_chat_inbox(session: AsyncSession, days: int) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = await session.execute(
        delete(ChatMessageInbox).where(ChatMessageInbox.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def run_retention_cleanup(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Один проход очистки. Возвращает счётчики удалённого по каждой категории."""
    counts: dict[str, int] = {}
    async with session_factory() as session:
        counts["llm_call_log"] = await purge_old_llm_calls(session, settings.retention_llm_call_log_days)
        counts["audit_log"] = await purge_old_audit_log(session, settings.retention_audit_log_days)
        counts["message_text"] = await purge_old_chat_message_text(
            session, settings.retention_chat_message_text_days
        )
        counts["deleted_leads"] = await purge_deleted_leads(session, settings.retention_deleted_lead_days)
        counts["chat_inbox"] = await purge_old_chat_inbox(
            session, settings.retention_chat_message_text_days
        )
    total = sum(counts.values())
    if total:
        logger.info("Retention cleanup: %s", counts)
    return counts


async def retention_loop(
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: int | None = None,
) -> None:
    """Фоновый цикл очистки с graceful shutdown и защитой от сбоев."""
    interval = interval_seconds or settings.retention_cleanup_interval_seconds
    logger.info("Retention loop started (interval=%s sec)", interval)
    try:
        while True:
            try:
                await run_retention_cleanup(session_factory)
            except Exception as exc:
                logger.error("Retention cleanup iteration failed: %s", exc)
                capture_exception(exc)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Retention loop cancelled, shutting down gracefully")
                raise
    except asyncio.CancelledError:
        logger.info("Retention loop stopped")
        raise
