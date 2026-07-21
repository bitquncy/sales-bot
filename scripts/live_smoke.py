"""Safe live smoke test for the personal deployment.

Uses real configured services but writes database checks to a temporary SQLite
database by default. It never prints tokens, API keys, prompts, or raw model
responses. Chat Monitor is intentionally not started because authorization can
change the Telethon session and require a Telegram code.

Run: ``python -m scripts.live_smoke``
"""

from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-telegram", action="store_true")
    parser.add_argument("--skip-overpass", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-redis", action="store_true")
    parser.add_argument("--city", default="Астана")
    parser.add_argument("--category", default="cafe")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def _configure_temp_db() -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="sales_agent_smoke_", suffix=".db")
    os.close(fd)
    path = Path(raw_path)
    path.unlink()
    os.environ["DB_URL"] = f"sqlite+aiosqlite:///{path.as_posix()}"
    return path


def _telegram_get_me(token: str) -> tuple[bool, str]:
    if not token:
        return False, "BOT_TOKEN is empty"
    connection = http.client.HTTPSConnection("api.telegram.org", timeout=15)
    try:
        connection.request("GET", f"/bot{token}/getMe")
        response = connection.getresponse()
        body = response.read(4096)
        if response.status != 200:
            return False, f"Telegram HTTP {response.status}"
        payload = json.loads(body.decode("utf-8"))
        if not payload.get("ok"):
            return False, "Telegram returned ok=false"
        return True, "Bot API getMe passed"
    except (OSError, ValueError) as exc:
        return False, f"Telegram request failed: {type(exc).__name__}"
    finally:
        connection.close()


def _print_result(checks: list[tuple[str, bool, str]], elapsed: float) -> int:
    print("Live smoke test")
    print("=" * 40)
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    passed = all(ok for _, ok, _ in checks)
    print(f"Elapsed: {elapsed:.1f}s")
    print("RESULT: PASS" if passed else "RESULT: FAIL")
    return 0 if passed else 1


async def _run(args: argparse.Namespace) -> int:
    db_path = _configure_temp_db()
    from config import settings
    from db import repo
    from db.base import engine, init_db, session_factory
    from services.ai import AIError, analyze_company, generate_messages
    from services.places import CATEGORIES, PlacesError, search_companies
    from utils.redis_client import get_redis

    checks: list[tuple[str, bool, str]] = []
    started = time.monotonic()
    try:
        await init_db()
        async with session_factory() as session:
            lead = await repo.create_lead(session, 987654321, "Smoke Test Company", "Test address")
            loaded = await repo.get_lead(session, lead.id, 987654321)
        checks.append(("database", loaded is not None, "temporary SQLite schema and CRUD"))

        if not args.skip_telegram:
            checks.append(("telegram", *_telegram_get_me(settings.bot_token)))

        if not args.skip_redis:
            if not settings.redis_url:
                checks.append(("redis", True, "not configured; skipped"))
            else:
                redis = await get_redis()
                ok = bool(redis is not None and await redis.ping())
                checks.append(("redis", ok, "PING passed" if ok else "PING failed"))

        if not args.skip_overpass:
            if args.category not in CATEGORIES:
                checks.append(("overpass", False, f"unknown category: {args.category}"))
            else:
                try:
                    companies = await search_companies(args.city, args.category)
                    checks.append(("overpass", True, f"parsed {len(companies)} named result(s)"))
                except PlacesError as exc:
                    checks.append(("overpass", False, str(exc)))

        if not args.skip_llm:
            if not settings.llm_ready:
                checks.append(("llm", False, "provider/key is not configured"))
            else:
                try:
                    score, analysis, has_booking = await analyze_company(
                        "Smoke Test Company", address="Test address", website=None
                    )
                    short, long = await generate_messages("Smoke Test Company", analysis)
                    ok = bool(
                        0 <= score <= 100
                        and analysis.strip()
                        and isinstance(has_booking, (bool, type(None)))
                        and short.strip()
                        and long.strip()
                    )
                    checks.append(("llm", ok, "analysis and generation passed"))
                except AIError as exc:
                    checks.append(("llm", False, f"{type(exc).__name__}: {exc}"))
        return _print_result(checks, time.monotonic() - started)
    finally:
        await engine.dispose()
        if args.keep_db:
            print(f"Temporary smoke DB kept at: {db_path}")
        else:
            db_path.unlink(missing_ok=True)
            Path(f"{db_path}-wal").unlink(missing_ok=True)
            Path(f"{db_path}-shm").unlink(missing_ok=True)


def main() -> int:
    try:
        return asyncio.run(_run(_parse_args()))
    except KeyboardInterrupt:
        print("RESULT: INTERRUPTED", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"RESULT: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
