"""Лёгкий клиент Telegram Bot API для процессов без aiogram (runner.py, cron-скрипты).

Использует aiohttp напрямую — не зависит от aiogram Bot/Dispatcher,
что позволяет вызывать Bot API из отдельного процесса (Telethon runner).
"""

import logging

import aiohttp

logger = logging.getLogger(__name__)


async def send_bot_message(
    bot_token: str,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
) -> bool:
    """Отправляет сообщение через Bot API. Возвращает True при успехе.

    Best-effort: ошибки логируются, но не бросаются наверх —
    уведомление не должно ломать основной процесс.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": parse_mode,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Bot API sendMessage failed (HTTP %s): %s", resp.status, body[:200])
                    return False
                return True
    except Exception as exc:
        logger.error("Bot API sendMessage error: %s", exc)
        return False
