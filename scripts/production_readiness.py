"""Fail-closed production readiness check (no secret values are printed)."""

import asyncio
import io
import subprocess
import zipfile

from dotenv import dotenv_values

from config import settings
from db.base import verify_schema
from utils.config_validator import validate_config
from utils.redis_client import get_redis


def _known_leaked_token_reused() -> bool:
    """Compare current token with historic leaked archive, if Git history exists."""
    try:
        archive = subprocess.check_output(
            ["git", "show", "fc8bcea:project.zip"], stderr=subprocess.DEVNULL
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            leaked = dotenv_values(stream=io.StringIO(zf.read(".env").decode("utf-8-sig")))
        return bool(
            leaked.get("BOT_TOKEN")
            and settings.bot_token
            and leaked["BOT_TOKEN"] == settings.bot_token
        )
    except Exception:
        # History may already be cleaned or unavailable in a Docker image.
        return False


async def main() -> int:
    errors = validate_config(settings)
    if settings.environment.lower() != "production":
        errors.append("ENVIRONMENT must be production for readiness check.")
    if _known_leaked_token_reused():
        errors.append("Current BOT_TOKEN matches the token leaked in historic project.zip.")
    try:
        await verify_schema()
    except Exception as exc:
        errors.append(f"Database schema check failed: {exc}")
    try:
        redis = await get_redis()
        if redis is None or not await redis.ping():
            errors.append("Redis check failed.")
    except Exception as exc:
        errors.append(f"Redis check failed: {type(exc).__name__}")

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    print("[OK] Production readiness checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
