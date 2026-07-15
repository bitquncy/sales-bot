"""CLI-запуск Telethon userbot для пассивного мониторинга чатов."""

import asyncio
import logging

from config import settings
from chat_monitor.config_store import ChatMonitorConfig, normalize_chat_ref
from db.base import init_db, session_factory
from chat_monitor.processor import candidate_from_event, process_candidate
from db import repo
from services.ai import AIError

logger = logging.getLogger(__name__)


def _ensure_ready() -> None:
    if not (
        settings.chat_monitor_owner_tg_id
        and settings.chat_monitor_api_id
        and settings.chat_monitor_api_hash
        and settings.chat_monitor_phone
        and settings.chat_monitor_session_path
    ):
        raise RuntimeError(
            "Chat monitor is not configured. Set CHAT_MONITOR_OWNER_TG_ID, "
            "CHAT_MONITOR_API_ID, CHAT_MONITOR_API_HASH, CHAT_MONITOR_PHONE, "
            "and CHAT_MONITOR_SESSION_PATH in .env. Chats/threshold can be set in the bot UI."
        )
    if not settings.llm_ready:
        raise RuntimeError("LLM provider is not configured for chat monitor scoring.")


def _env_default_chats() -> list[str]:
    return [str(chat) for chat in settings.chat_monitor_chat_list]


def _mask_phone(phone: str) -> str:
    phone = normalize_phone(phone)
    if len(phone) <= 4:
        return "****"
    return "*" * (len(phone) - 4) + phone[-4:]


def normalize_phone(phone: str) -> str:
    """Telethon надёжнее авторизуется с номером без пробелов/скобок/дефисов."""
    phone = phone.strip()
    if not phone:
        return phone
    prefix = "+" if phone.startswith("+") else ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return prefix + digits


async def load_runtime_config() -> ChatMonitorConfig:
    async with session_factory() as session:
        row = await repo.get_or_create_chat_monitor_settings(
            session,
            settings.chat_monitor_owner_tg_id,
            default_chats=_env_default_chats(),
            default_min_score=settings.chat_monitor_min_score,
        )
        return repo.chat_monitor_settings_to_config(row)


async def event_matches_chat_refs(event, chat_refs: list[str]) -> bool:
    chat_id = getattr(event, "chat_id", None)
    chat = await event.get_chat()
    username = getattr(chat, "username", None)
    username = username.lower() if username else None

    for raw_ref in chat_refs:
        ref = normalize_chat_ref(raw_ref)
        if not ref:
            continue
        if ref.lstrip("-").isdigit():
            if chat_id is not None and int(ref) == int(chat_id):
                return True
            continue
        if username and ref.lstrip("@").lower() == username:
            return True
    return False


async def _heartbeat_loop() -> None:
    """P-4: Периодически пишет timestamp в heartbeat-файл."""
    from datetime import datetime, timezone

    interval = settings.heartbeat_interval_minutes * 60
    while True:
        try:
            ts = datetime.now(timezone.utc).isoformat()
            with open(settings.heartbeat_file, "w", encoding="utf-8") as f:
                f.write(ts)
            logger.debug("Heartbeat written: %s", ts)
        except Exception:
            logger.debug("Failed to write heartbeat", exc_info=True)
        await asyncio.sleep(interval)


async def run() -> None:
    _ensure_ready()
    try:
        from telethon import TelegramClient, events
    except ImportError as exc:
        raise RuntimeError("Telethon is not installed. Run `pip install -r requirements-lock.txt`.") from exc

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await init_db()

    client = TelegramClient(
        settings.chat_monitor_session_path,
        settings.chat_monitor_api_id,
        settings.chat_monitor_api_hash,
    )

    initial_config = await load_runtime_config()
    logger.info(
        "Chat monitor config loaded: enabled=%s chats=%s min_score=%.2f",
        initial_config.is_enabled,
        len(initial_config.chats),
        initial_config.min_score,
    )

    @client.on(events.NewMessage())
    async def on_new_message(event) -> None:
        try:
            config = await load_runtime_config()
            if not config.is_enabled or not config.chats:
                return
            if not await event_matches_chat_refs(event, config.chats):
                return
            candidate = await candidate_from_event(event)
            if candidate is None:
                return
            lead = await process_candidate(
                candidate,
                session_factory,
                owner_tg_id=config.owner_tg_id,
                min_score=config.min_score,
            )
        except AIError as exc:
            logger.warning("LLM parsing error while processing chat monitor message: %s", exc)
            return
        except Exception:
            logger.exception("Failed to process chat monitor message")
            return
        if lead is not None:
            logger.info("Saved chat lead id=%s source_chat=%s", lead.id, lead.source_chat)

    logger.info(
        "Starting Telethon authorization for phone ending %s. The login code is usually sent "
        "to the official Telegram app first, not always by SMS. force_sms=%s",
        _mask_phone(settings.chat_monitor_phone),
        settings.chat_monitor_force_sms,
    )
    await client.start(
        phone=normalize_phone(settings.chat_monitor_phone),
        force_sms=settings.chat_monitor_force_sms,
    )
    me = await client.get_me()
    logger.info(
        "Chat monitor started as user_id=%s username=%s",
        getattr(me, "id", None),
        getattr(me, "username", None),
    )

    # P-4: Запускаем heartbeat-задачу параллельно с Telethon
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        await client.run_until_disconnected()
    finally:
        heartbeat_task.cancel()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
