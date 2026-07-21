"""Разовое шифрование существующих plaintext `leads.message_text`.

Зачем: после включения PII_ENCRYPTION_KEY новые значения `message_text`
шифруются автоматически через `EncryptedText`, но уже существующие строки в БД
могут оставаться plaintext. Этот скрипт находит такие строки и заменяет их
Fernet-шифротекстом.

Безопасный режим по умолчанию: без `--apply` только dry-run.

Примеры:
    python -m scripts.encrypt_existing
    python -m scripts.encrypt_existing --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Позволяем запуск из корня проекта и как `python scripts/encrypt_existing.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from db.base import init_db, session_factory
from utils.crypto import ENC_PREFIX, encrypt_value


async def encrypt_plaintext_message_texts(
    factory: async_sessionmaker[AsyncSession],
    dry_run: bool = True,
) -> dict[str, int]:
    """Шифрует plaintext-строки `leads.message_text`.

    Возвращает счётчики:
      total_with_text — строк с непустым message_text;
      already_encrypted — уже с префиксом ENC_PREFIX;
      to_encrypt — plaintext-кандидаты;
      encrypted — реально обновлено (0 в dry-run).
    """
    async with factory() as session:
        rows = (await session.execute(text(
            "SELECT id, message_text FROM leads "
            "WHERE message_text IS NOT NULL AND message_text != ''"
        ))).all()

        total = len(rows)
        already = 0
        candidates: list[tuple[int, str]] = []
        for row in rows:
            lead_id = int(row._mapping["id"])
            value = str(row._mapping["message_text"])
            if value.startswith(ENC_PREFIX):
                already += 1
            else:
                candidates.append((lead_id, value))

        if dry_run:
            return {
                "total_with_text": total,
                "already_encrypted": already,
                "to_encrypt": len(candidates),
                "encrypted": 0,
            }

        encrypted_count = 0
        for lead_id, plaintext in candidates:
            encrypted = encrypt_value(plaintext)
            if not encrypted or not encrypted.startswith(ENC_PREFIX):
                raise RuntimeError(
                    "PII encryption did not produce encrypted value. "
                    "Check PII_ENCRYPTION_KEY."
                )
            await session.execute(
                text("UPDATE leads SET message_text = :message_text WHERE id = :id"),
                {"message_text": encrypted, "id": lead_id},
            )
            encrypted_count += 1
        await session.commit()

        return {
            "total_with_text": total,
            "already_encrypted": already,
            "to_encrypt": len(candidates),
            "encrypted": encrypted_count,
        }


def _validate_encryption_key() -> None:
    if not settings.pii_encryption_key:
        raise SystemExit(
            "PII_ENCRYPTION_KEY is not set. Generate one with:\n"
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    sample = encrypt_value("self-test")
    if not sample or not sample.startswith(ENC_PREFIX):
        raise SystemExit("PII_ENCRYPTION_KEY is invalid or encryption is unavailable.")


async def _main_async(apply: bool) -> int:
    _validate_encryption_key()
    await init_db()
    counts = await encrypt_plaintext_message_texts(session_factory, dry_run=not apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"encrypt_existing: {mode}")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    if not apply and counts["to_encrypt"]:
        print("Run with --apply to encrypt plaintext rows.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypt existing plaintext leads.message_text rows")
    parser.add_argument("--apply", action="store_true", help="actually update DB (default: dry-run)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args.apply)))


if __name__ == "__main__":
    main()
