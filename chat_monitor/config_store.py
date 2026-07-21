"""Хранение и нормализация пользовательских настроек Chat Monitor."""

import json
import re
from dataclasses import dataclass
from typing import Iterable

DEFAULT_MIN_SCORE = 0.7
MAX_CHAT_REF_LENGTH = 64
_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{3,32}$")
_CHAT_ID_RE = re.compile(r"^-?\d{1,20}$")


@dataclass(slots=True)
class ChatMonitorConfig:
    owner_tg_id: int
    is_enabled: bool
    chats: list[str]
    min_score: float


def normalize_chat_ref(raw: str) -> str | None:
    """Нормализует chat username/id из ввода пользователя."""
    value = raw.strip()
    if not value:
        return None
    value = value.replace("https://t.me/", "").replace("http://t.me/", "")
    value = value.replace("t.me/", "")
    value = value.split("?", 1)[0].strip().rstrip("/")
    if not value or len(value) > MAX_CHAT_REF_LENGTH:
        return None
    if _CHAT_ID_RE.fullmatch(value):
        return value
    if value.startswith("@"):
        value = value[1:]
    if not value:
        return None
    value = f"@{value}"
    return value if _USERNAME_RE.fullmatch(value) else None


def parse_chat_refs(text: str, max_refs: int = 100) -> list[str]:
    """Парсит usernames/chat_id из строки, разделённой запятыми или переносами."""
    refs: list[str] = []
    for part in text.replace("\n", ",").split(","):
        normalized = normalize_chat_ref(part)
        if normalized and normalized not in refs:
            refs.append(normalized)
            if len(refs) >= max_refs:
                break
    return refs


def serialize_chat_refs(chats: Iterable[str]) -> str:
    normalized: list[str] = []
    for chat in chats:
        value = normalize_chat_ref(str(chat))
        if value and value not in normalized:
            normalized.append(value)
    return json.dumps(normalized, ensure_ascii=False)


def deserialize_chat_refs(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return parse_chat_refs(raw)
    if not isinstance(data, list):
        return []
    return [value for value in (normalize_chat_ref(str(item)) for item in data) if value]


def parse_min_score(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", ".").strip())
    except ValueError:
        return None
    if not 0 <= value <= 1:
        return None
    return value
