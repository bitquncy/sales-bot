"""Проверка конфигурации для run.bat/run.sh теми же правилами, что bot.py."""

import asyncio

from config import settings
from utils.config_validator import validate_config


def check_config() -> bool:
    """Возвращает True, если конфигурация пригодна для запуска бота."""
    errors = validate_config(settings)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return False
    if not settings.llm_ready:
        print("[WARNING] LLM is not configured; AI features will be unavailable.")
    if settings.pii_encryption_key:
        # Валидация Fernet-ключа до старта, чтобы не писать ПДн в plaintext
        # из-за опечатки в PII_ENCRYPTION_KEY.
        from utils.crypto import ENC_PREFIX, encrypt_value, reset_fernet

        reset_fernet()
        encrypted = encrypt_value("config-self-test")
        if not encrypted or not encrypted.startswith(ENC_PREFIX):
            print("[ERROR] PII_ENCRYPTION_KEY is invalid.")
            return False
    if settings.environment.lower() == "production":
        from scripts.production_readiness import main as readiness_main

        return asyncio.run(readiness_main()) == 0
    print("[OK] Configuration valid")
    return True


if __name__ == "__main__":
    try:
        raise SystemExit(0 if check_config() else 1)
    except Exception as exc:
        print(f"[ERROR] Config check failed: {exc}")
        raise SystemExit(1) from exc
