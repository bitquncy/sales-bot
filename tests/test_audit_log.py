"""Тесты audit log (AUDIT-1): запись действий и best-effort поведение."""

from sqlalchemy import select

from db import repo
from db.models import AuditLog

OWNER = 555_000_111


async def _audit_rows(session, action: str | None = None):
    query = select(AuditLog).where(AuditLog.owner_tg_id == OWNER)
    if action:
        query = query.where(AuditLog.action == action)
    result = await session.execute(query)
    return list(result.scalars().all())


async def test_log_action_writes_row(session):
    await repo.log_action(session, OWNER, "status_changed", lead_id=42, details="written")

    rows = await _audit_rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "status_changed"
    assert row.lead_id == 42
    assert row.details == "written"
    assert row.created_at is not None


async def test_log_action_without_optional_fields(session):
    await repo.log_action(session, OWNER, "export_csv")

    rows = await _audit_rows(session)
    assert len(rows) == 1
    assert rows[0].lead_id is None
    assert rows[0].details is None


async def test_log_action_is_best_effort(session):
    """Сбой аудита (невалидные данные) не должен ломать вызывающий код."""
    # Передаём action=None — нарушение NOT NULL должно быть проглочено
    await repo.log_action(session, OWNER, None)  # type: ignore[arg-type]
    # Не упало — уже хорошо; сессия остаётся рабочей после rollback
    lead = await repo.create_lead(session, OWNER, "After failed audit")
    assert lead.id is not None


async def test_status_change_writes_audit(session):
    """Связка repo-операции и аудита (как в handlers/crm.change_status)."""
    lead = await repo.create_lead(session, OWNER, "Audit Co")
    await repo.set_lead_status(session, lead.id, OWNER, "client")
    await repo.log_action(session, OWNER, "status_changed", lead.id, details="client")

    rows = await _audit_rows(session, "status_changed")
    assert len(rows) == 1
    assert rows[0].lead_id == lead.id
    assert rows[0].details == "client"


async def test_audit_scoped_by_owner(session):
    await repo.log_action(session, OWNER, "lead_deleted", 1)
    await repo.log_action(session, OWNER + 1, "lead_deleted", 2)

    mine = await _audit_rows(session)
    assert len(mine) == 1
    assert mine[0].lead_id == 1
