"""Keyword-фильтр для Chat Lead Monitor."""

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
