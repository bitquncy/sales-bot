"""Лёгкий клиент Telegram Bot API для процессов без aiogram (runner.py, cron-скрипты).

Использует aiohttp напрямую — не зависит от aiogram Bot/Dispatcher,
что позволяет вызывать Bot API из отдельного процесса (Telethon runner).
"""

import logging
import asyncio

import aiohttp

logger = logging.getLogger(__name__)


def _mask_token(token: str) -> str:
    """Маскирует токен бота для безопасного логирования (S-2)."""
    if len(token) <= 8:
        return "***"
    return token[:4] + "***" + token[-4:]


async def send_bot_message(
    bot_token: str,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
) -> bool:
    """Отправляет сообщение через Bot API. Возвращает True при успехе.

    Best-effort: ошибки логируются, но не бросаются наверх —
    уведомление не должно ломать основной процесс.
    Токен в логах маскируется (S-2).
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": parse_mode,
    }
    from config import settings

    attempts = max(1, settings.external_retry_attempts + 1)
    try:
        async with aiohttp.ClientSession() as session:
            for attempt in range(attempts):
                try:
                    async with session.post(
                        url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        if resp.status == 200:
                            return True
                        if resp.status < 500 and resp.status != 429:
                            body = await resp.text()
                            logger.error(
                                "Bot API sendMessage failed (HTTP %s) token=%s chat_id=%s: %s",
                                resp.status, _mask_token(bot_token), chat_id, body[:200],
                            )
                            return False
                        if attempt + 1 >= attempts:
                            logger.error(
                                "Bot API sendMessage exhausted retries (HTTP %s) chat_id=%s",
                                resp.status, chat_id,
                            )
                            return False
                        retry_after = resp.headers.get("Retry-After")
                        try:
                            delay = max(0.0, float(retry_after)) if retry_after else None
                        except ValueError:
                            delay = None
                        await asyncio.sleep(
                            delay if delay is not None else
                            settings.external_retry_base_delay_seconds * (2 ** attempt)
                        )
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    if attempt + 1 >= attempts:
                        logger.error("Bot API sendMessage error (chat_id=%s): %s", chat_id, exc)
                        return False
                    await asyncio.sleep(
                        settings.external_retry_base_delay_seconds * (2 ** attempt)
                    )
    except Exception as exc:
        logger.error("Bot API sendMessage setup error (chat_id=%s): %s", chat_id, exc)
        return False
    return False
