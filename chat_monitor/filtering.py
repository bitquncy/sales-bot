"""Keyword-фильтр для Chat Lead Monitor."""

import time
from collections.abc import Iterable

from chat_monitor.keywords_nail import KEYWORDS


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def find_keywords(text: str, keywords: Iterable[str] = KEYWORDS) -> list[str]:
    """Возвращает ключи, найденные в тексте, без сетевых/LLM-вызовов."""
    normalized_text = _normalize(text)
    matches: list[str] = []
    for keyword in keywords:
        normalized_keyword = _normalize(keyword)
        if normalized_keyword and normalized_keyword in normalized_text:
            matches.append(keyword)
    return matches


def passes_keyword_filter(text: str, keywords: Iterable[str] = KEYWORDS) -> bool:
    return bool(find_keywords(text, keywords))


# --------------------------------------------------------------------------- #
#  CHATMON-1: Cooldown на автора (защита LLM-бюджета от флуда одним автором)
# --------------------------------------------------------------------------- #

# Максимум записей в словаре cooldown; при превышении чистим устаревшие.
_MAX_COOLDOWN_ENTRIES = 10_000

# author_id -> timestamp последнего скоринга (in-memory: при рестарте бота
# cooldown сбрасывается — приемлемо, худший случай это лишний LLM-вызов
# на автора, а не потеря данных).
_author_last_scored: dict[int, float] = {}


def author_on_cooldown(
    author_id: int,
    cooldown_seconds: int,
    now: float | None = None,
) -> bool:
    """True, если автор уже скорился недавно (LLM-вызов по нему нужно пропустить).

    При отрицательном результате метка времени ОБНОВЛЯЕТСЯ — то есть вызов
    функции означает «сейчас будем скорить этого автора». cooldown_seconds <= 0
    отключает ограничение.
    """
    if cooldown_seconds <= 0:
        return False
    now = time.time() if now is None else now
    last = _author_last_scored.get(author_id)
    if last is not None and now - last < cooldown_seconds:
        return True
    _author_last_scored[author_id] = now
    # Очистка, чтобы словарь не рос бесконечно на активных чатах
    if len(_author_last_scored) > _MAX_COOLDOWN_ENTRIES:
        cutoff = now - cooldown_seconds
        for key in [k for k, ts in _author_last_scored.items() if ts < cutoff]:
            del _author_last_scored[key]
    return False


def reset_author_cooldowns() -> None:
    """Сбрасывает cooldown всех авторов (для тестов)."""
    _author_last_scored.clear()
