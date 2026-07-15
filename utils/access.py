"""Контроль доступа: allowlist пользователей бота (P-1).

Если ALLOWED_USER_IDS задан и не пуст — бот отвечает только перечисленным
пользователям. Пусто = доступ не ограничен (личный бот).
"""

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from config import settings
from utils.emoji_config import E

NOT_ALLOWED_TEXT = (
    f"{E.CROSS} У вас нет доступа к этому боту. "
    "Если это ваш бот — добавьте свой Telegram ID в ALLOWED_USER_IDS в .env."
)


def is_user_allowed(tg_user_id: int) -> bool:
    """True, если пользователь имеет доступ к боту."""
    allowed = settings.allowed_user_set
    return not allowed or tg_user_id in allowed


class AllowlistMiddleware(BaseMiddleware):
    """Middleware: блокирует неавторизованных пользователей.

    Регистрируется как outer middleware на dispatcher, чтобы перехватывать
    все входящие сообщения и callback-и до того, как они дойдут до хендлеров.
    """

    async def __call__(self, handler, event: TelegramObject, data):
        user = data.get("event_from_user")
        if user is not None and not is_user_allowed(user.id):
            # Для CallbackQuery event.message — исходное сообщение,
            # для Message event.message не существует -> используем сам event.
            message = getattr(event, "message", None) or event
            if hasattr(message, "answer"):
                try:
                    await message.answer(NOT_ALLOWED_TEXT)
                except Exception:
                    pass
            return None
        return await handler(event, data)
