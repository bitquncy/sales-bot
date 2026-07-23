"""QR-авторизация Telethon-сессии без SMS/кода.

Запуск:
    python scripts/telethon_qr_login.py

Сканировать QR нужно из Telegram: Settings -> Devices -> Link Desktop Device.
Секреты берутся из .env, QR-файл создаётся локально и удаляется после успеха.
"""

import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from utils.file_perms import restrict_file_permissions  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

QR_PATH = ROOT / "chat_monitor_qr.png"


def _ensure_ready() -> None:
    missing = []
    if not settings.chat_monitor_api_id:
        missing.append("CHAT_MONITOR_API_ID")
    if not settings.chat_monitor_api_hash:
        missing.append("CHAT_MONITOR_API_HASH")
    if not settings.chat_monitor_session_path:
        missing.append("CHAT_MONITOR_SESSION_PATH")
    if missing:
        raise RuntimeError(f"Missing Telethon config: {', '.join(missing)}")


def _open_file(path: Path) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        logger.info("QR image saved: %s", path)


async def main() -> None:
    _ensure_ready()
    client = TelegramClient(
        settings.chat_monitor_session_path,
        settings.chat_monitor_api_id,
        settings.chat_monitor_api_hash,
    )
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info("Session already authorized: user_id=%s username=%s", me.id, me.username)
            return

        qr = await client.qr_login()
        img = qrcode.make(qr.url)
        img.save(QR_PATH)
        _open_file(QR_PATH)
        logger.info("Scan %s in Telegram: Settings -> Devices -> Link Desktop Device", QR_PATH)
        logger.info("Waiting for scan. QR expires at %s", qr.expires)

        try:
            await qr.wait(timeout=120)
        except SessionPasswordNeededError:
            password = getpass.getpass("Two-step verification password: ")
            await client.sign_in(password=password)

        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info("QR login successful: user_id=%s username=%s", me.id, me.username)
            restrict_file_permissions(settings.chat_monitor_session_path)
            try:
                QR_PATH.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            logger.error("QR login finished but session is not authorized")
    finally:
        try:
            QR_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
