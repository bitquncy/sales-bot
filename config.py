"""Конфигурация приложения через pydantic-settings.

ВАЖНО: bot_token намеренно имеет дефолт "" — иначе импорт конфига
(например, в тестах) падает без .env. Проверка на пустой токен
выполняется в bot.py перед стартом polling.

LLM-провайдер переключается через .env (LLM_PROVIDER):
  * "anthropic"  — Anthropic Claude SDK (платный, был исходным);
  * "openrouter" — любой OpenAI-совместимый эндпоинт (OpenRouter, Moonshot,
    локальный сервер и т.п.). Модель/URL/ключ задаются LLM_* переменными.
Anthropic остаётся доступным всегда — это настройка, а не необратимая миграция.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""

    # --- Выбор LLM-провайдера ---
    # "anthropic" | "openrouter" (или любой другой OpenAI-совместимый провайдер)
    llm_provider: str = "anthropic"
    # Имя модели у выбранного провайдера. Для openrouter, напр. moonshotai/kimi-k2.6:free.
    # Намеренно без дефолта-хардкода конкретной модели — задаётся в .env.
    llm_model: str = ""
    # base_url для OpenAI-совместимого провайдера (для anthropic не используется).
    llm_base_url: str = "https://openrouter.ai/api/v1"
    # Ключ выбранного провайдера. Для anthropic, если пусто, берётся ANTHROPIC_API_KEY.
    llm_api_key: str = ""
    # Таймаут одного запроса к LLM, секунды. Бесплатные модели отвечают
    # медленнее — поэтому значение настраиваемое, а не хардкод на оба провайдера.
    llm_timeout_seconds: float = 60.0

    # --- Legacy Anthropic (используются, когда llm_provider=anthropic) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    db_url: str = "sqlite+aiosqlite:///./sales_agent.db"

    # Интервал фонового поллера напоминаний, секунды
    reminders_poll_interval: int = 60

    # --- Chat Lead Monitor (Telethon userbot) ---
    # Лиды из чатов должны попадать в CRM конкретного владельца бота.
    chat_monitor_owner_tg_id: int = 0
    chat_monitor_api_id: int = 0
    chat_monitor_api_hash: str = ""
    chat_monitor_phone: str = ""
    chat_monitor_session_path: str = "chat_monitor.session"
    # Если Telegram не присылает код в приложение, можно попробовать принудительный SMS.
    chat_monitor_force_sms: bool = False
    # Comma-separated usernames/ids: @chat_one,-1001234567890
    chat_monitor_chats: str = ""
    chat_monitor_min_score: float = 0.7

    # --- Производные значения (учитывают legacy-переменные) ---

    @property
    def resolved_anthropic_key(self) -> str:
        """Ключ для Anthropic: приоритет у LLM_API_KEY, затем ANTHROPIC_API_KEY."""
        return self.llm_api_key or self.anthropic_api_key

    @property
    def resolved_anthropic_model(self) -> str:
        """Модель для Anthropic: приоритет у LLM_MODEL, затем ANTHROPIC_MODEL."""
        return self.llm_model or self.anthropic_model

    @property
    def llm_ready(self) -> bool:
        """Есть ли ключ, достаточный для работы выбранного провайдера."""
        if self.llm_provider.lower() == "anthropic":
            return bool(self.resolved_anthropic_key)
        return bool(self.llm_api_key)

    @property
    def chat_monitor_chat_list(self) -> list[int | str]:
        """Список чатов для Telethon из CHAT_MONITOR_CHATS.

        Числовые id приводим к int, usernames оставляем строками. Пустые элементы
        игнорируются, чтобы удобно редактировать .env без правки кода.
        """
        chats: list[int | str] = []
        for raw in self.chat_monitor_chats.split(","):
            value = raw.strip()
            if not value:
                continue
            if value.lstrip("-").isdigit():
                chats.append(int(value))
            else:
                chats.append(value)
        return chats

    @property
    def chat_monitor_ready(self) -> bool:
        """Достаточен ли конфиг для запуска Telethon-монитора."""
        return bool(
            self.chat_monitor_owner_tg_id
            and self.chat_monitor_api_id
            and self.chat_monitor_api_hash
            and self.chat_monitor_phone
            and self.chat_monitor_session_path
            and self.chat_monitor_chat_list
        )


settings = Settings()
