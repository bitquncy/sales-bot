"""Отправка сообщений с кастомными эмодзи и авто-fallback на обычный юникод.

Если Telegram отклонит сообщение из-за невалидного/удалённого emoji-id
(TelegramBadRequest, например EMOJI_INVALID), тот же текст отправляется
повторно с <tg-emoji ...>X</tg-emoji>, заменённым на plain-эквивалент X.
Пользователь никогда не остаётся без ответа из-за эмодзи.
"""

import logging
from html import unescape
import re

from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>')
_HTML_TAG_RE = re.compile(r"<[^>]+>")

TELEGRAM_MESSAGE_LIMIT = 4096
TRUNCATED_SUFFIX = "\n\n… текст обрезан"


def strip_custom_emojis(text: str) -> str:
    """Заменяет все <tg-emoji ...>X</tg-emoji> на plain-эмодзи X."""
    return _TG_EMOJI_RE.sub(r"\1", text or "")


def strip_html_tags(text: str) -> str:
    """Plain-text fallback, если Telegram отклонил HTML-разметку."""
    return unescape(_HTML_TAG_RE.sub("", text or ""))


def truncate_telegram_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Гарантирует, что текст не превысит лимит Telegram на одно сообщение."""
    text = text or ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATED_SUFFIX):
        return text[:limit]
    return text[: limit - len(TRUNCATED_SUFFIX)].rstrip() + TRUNCATED_SUFFIX


def _plain_fallback_kwargs(kwargs: dict) -> dict:
    fallback_kwargs = dict(kwargs)
    fallback_kwargs["parse_mode"] = None
    return fallback_kwargs


async def safe_answer(message, text: str, **kwargs):
    """message.answer с fallback на plain-эмодзи при TelegramBadRequest."""
    text = truncate_telegram_text(text)
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("answer failed (%s), retrying with plain emojis", exc)
        plain_emoji_text = truncate_telegram_text(strip_custom_emojis(text))
        try:
            return await message.answer(plain_emoji_text, **kwargs)
        except TelegramBadRequest as second_exc:
            logger.warning("answer fallback failed (%s), retrying as plain text", second_exc)
            return await message.answer(
                truncate_telegram_text(strip_html_tags(plain_emoji_text)),
                **_plain_fallback_kwargs(kwargs),
            )


async def safe_edit(message, text: str, **kwargs):
    """message.edit_text с fallback на plain-эмодзи при TelegramBadRequest."""
    text = truncate_telegram_text(text)
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("edit_text failed (%s), retrying with plain emojis", exc)
        plain_emoji_text = truncate_telegram_text(strip_custom_emojis(text))
        try:
            return await message.edit_text(plain_emoji_text, **kwargs)
        except TelegramBadRequest as second_exc:
            logger.warning("edit_text fallback failed (%s), retrying as plain text", second_exc)
            return await message.edit_text(
                truncate_telegram_text(strip_html_tags(plain_emoji_text)),
                **_plain_fallback_kwargs(kwargs),
            )


async def safe_bot_send(bot, chat_id: int, text: str, **kwargs):
    """bot.send_message с fallback на plain-эмодзи при TelegramBadRequest."""
    text = truncate_telegram_text(text)
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("send_message failed (%s), retrying with plain emojis", exc)
        plain_emoji_text = truncate_telegram_text(strip_custom_emojis(text))
        try:
            return await bot.send_message(chat_id, plain_emoji_text, **kwargs)
        except TelegramBadRequest as second_exc:
            logger.warning("send_message fallback failed (%s), retrying as plain text", second_exc)
            return await bot.send_message(
                chat_id,
                truncate_telegram_text(strip_html_tags(plain_emoji_text)),
                **_plain_fallback_kwargs(kwargs),
            )
