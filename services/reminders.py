"""Фоновый поллер напоминаний.

ВАЖНО: is_sent помечается ДО отправки сообщения — иначе при рестарте
бота в момент отправки напоминание уйдёт повторно.

При ЯВНОМ сбое отправки (Telegram API недоступен, сеть) is_sent
откатывается обратно на False — поллер повторит попытку на следующей
итерации. Риск дубля остаётся только в редком случае «сообщение дошло,
но ответ API оборвался» — приемлемо для личного бота, потеря
напоминания хуже дубля.
"""

import asyncio
import logging
from html import escape

from db import repo
from utils.emoji_config import E
from utils.safe_send import safe_bot_send

logger = logging.getLogger(__name__)


async def poll_reminders_once(bot, session_factory) -> int:
    """Один проход: отправить все просроченные неотправленные напоминания.

    Лид загружается через selectinload в get_due_reminders — нет N+1 запросов (CODE-3).
    Возвращает число обработанных напоминаний.
    """
    processed = 0
    async with session_factory() as session:
        due = await repo.get_due_reminders(session)
        for reminder in due:
            # Сначала помечаем отправленным, потом шлём (защита от дублей при рестарте).
            await repo.mark_reminder_sent(session, reminder.id)
            processed += 1

            # Лид уже предзагружен через selectinload — нет дополнительного запроса
            lead = reminder.lead
            lead_name = lead.name if lead else f"лид #{reminder.lead_id}"
            text = f"{E.TIMER} Напоминание по лиду <b>{escape(lead_name)}</b>"
            if reminder.text:
                text += f"\n{escape(reminder.text)}"
            try:
                # safe_bot_send: при невалидном emoji-id повторит с plain-эмодзи
                await safe_bot_send(bot, reminder.owner_tg_id, text)
            except Exception as exc:
                # Откатываем is_sent, чтобы поллер повторил попытку на следующей итерации.
                logger.error(
                    "Failed to send reminder id=%s: %s — rolling back is_sent, will retry",
                    reminder.id,
                    exc,
                )
                await repo.mark_reminder_unsent(session, reminder.id)
    return processed


async def reminders_loop(bot, session_factory, interval_seconds: int = 60) -> None:
    """Бесконечный цикл поллера. Любая ошибка логируется, цикл не умирает."""
    while True:
        try:
            await poll_reminders_once(bot, session_factory)
        except Exception as exc:
            logger.error("Reminders poll iteration failed: %s", exc)
        await asyncio.sleep(interval_seconds)
