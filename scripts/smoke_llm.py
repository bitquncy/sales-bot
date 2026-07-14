"""Живой (не моковый) прогон LLM-провайдера из .env. НЕ часть pytest.

Делает по одному реальному вызову analyze_company и generate_messages через
текущий настроенный провайдер (LLM_PROVIDER) и печатает СЫРОЙ ответ модели +
результат парсинга. Нужен, чтобы вручную убедиться, что ключ/модель/эндпоинт
настроены и модель отдаёт валидный JSON, — без запуска всего бота.

Запуск из корня проекта (с заполненным .env):
    py -3.11 scripts/smoke_llm.py

Коды возврата: 0 — оба вызова прошли; 1 — LLM не сконфигурирован;
2 — упал analyze_company; 3 — упал generate_messages.
"""

import asyncio
import sys
from pathlib import Path

# Чтобы скрипт запускался как `py -3.11 scripts/smoke_llm.py` из корня проекта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import ai  # noqa: E402


class _CapturingClient(ai.LLMClient):
    """Оборачивает реального клиента и запоминает последний сырой ответ модели.

    Промпты/парсинг остаются в базовом LLMClient — здесь только перехват
    _complete(), чтобы напечатать ровно то, что вернул провайдер.
    """

    def __init__(self, inner: ai.LLMClient) -> None:
        self._inner = inner
        self.last_raw: str | None = None

    async def _complete(self, prompt: str) -> str:
        raw = await self._inner._complete(prompt)
        self.last_raw = raw
        return raw


SAMPLE = {
    "name": "Барбершоп «Бородач»",
    "address": "ул. Баумана, 1, Казань",
    "phone": "+7 900 000-00-00",
    "website": None,
}


async def main() -> int:
    if not settings.llm_ready:
        print(
            f"[smoke] LLM не сконфигурирован: провайдер={settings.llm_provider!r}, ключ пуст. "
            "Заполни LLM_API_KEY (или ANTHROPIC_API_KEY) в .env.",
            file=sys.stderr,
        )
        return 1

    model = settings.llm_model or settings.resolved_anthropic_model
    print(f"[smoke] provider={settings.llm_provider!r} model={model!r}")
    client = _CapturingClient(ai.get_client())

    # --- analyze_company ---
    print("\n=== analyze_company ===")
    try:
        score, analysis, has_online_booking = await ai.analyze_company(**SAMPLE, client=client)
    except ai.AIError as exc:
        print(f"[smoke] analyze_company упал: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[smoke] сырой ответ модели:\n{client.last_raw!r}", file=sys.stderr)
        return 2
    print(f"--- сырой ответ модели ---\n{client.last_raw}")
    print(f"--- разобрано ---\nscore={score}\nhas_online_booking={has_online_booking}\nanalysis:\n{analysis}")

    # --- generate_messages (использует разбор предыдущего шага) ---
    print("\n=== generate_messages ===")
    try:
        short, long = await ai.generate_messages(SAMPLE["name"], analysis, client=client)
    except ai.AIError as exc:
        print(f"[smoke] generate_messages упал: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[smoke] сырой ответ модели:\n{client.last_raw!r}", file=sys.stderr)
        return 3
    print(f"--- сырой ответ модели ---\n{client.last_raw}")
    print(f"--- разобрано ---\nКОРОТКОЕ:\n{short}\n\nРАЗВЁРНУТОЕ:\n{long}")

    print("\n[smoke] OK — оба вызова прошли и распарсились.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
