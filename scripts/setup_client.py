"""Мастер быстрого подключения нового клиента (CONFIG-1).

Интерактивно задаёт вопросы, генерирует .env, проверяет подключение
к Telegram Bot API, запускает init_db.

Запуск:
    python scripts/setup_client.py
    python scripts/setup_client.py --output .env.client1
    python scripts/setup_client.py --non-interactive --env-file existing.env
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Позволяем запуск из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    """Задаёт вопрос пользователю. Возвращает введённое значение или default."""
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        value = input(display).strip()
        if not value:
            value = default
        if required and not value:
            print("  ⚠ Это поле обязательно. Введи значение.")
            continue
        return value


def _ask_bool(prompt: str, default: bool = False) -> bool:
    default_str = "y" if default else "n"
    value = _ask(f"{prompt} (y/n)", default=default_str)
    return value.lower() in ("y", "yes", "да", "1", "true")


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram Bot API check
# ─────────────────────────────────────────────────────────────────────────────

async def _check_bot_token(token: str) -> tuple[bool, str]:
    """Проверяет токен через getMe. Возвращает (ok, username_or_error)."""
    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{token}/getMe"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    username = data["result"].get("username", "unknown")
                    return True, f"@{username}"
                return False, data.get("description", "Unknown error")
    except Exception as exc:
        return False, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# DB init
# ─────────────────────────────────────────────────────────────────────────────

async def _init_database(db_url: str) -> tuple[bool, str]:
    """Инициализирует БД по указанному URL."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from db.base import Base, _ensure_lead_columns
        from db import models  # noqa: F401

        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_lead_columns)
        await engine.dispose()
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# .env generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_env(config: dict) -> str:
    """Генерирует содержимое .env файла из словаря конфига."""
    lines = [
        "# Сгенерировано scripts/setup_client.py",
        "# Отредактируй при необходимости.",
        "",
        "# ── Обязательные ──────────────────────────────────────────────",
        f"BOT_TOKEN={config['bot_token']}",
        "",
        "# ── LLM ───────────────────────────────────────────────────────",
        f"LLM_PROVIDER={config['llm_provider']}",
        f"LLM_API_KEY={config['llm_api_key']}",
        f"LLM_MODEL={config['llm_model']}",
        f"LLM_BASE_URL={config['llm_base_url']}",
        f"LLM_DAILY_LIMIT={config['llm_daily_limit']}",
        "",
        "# ── База данных ────────────────────────────────────────────────",
        f"DB_URL={config['db_url']}",
        "",
        "# ── Безопасность ───────────────────────────────────────────────",
        f"ALLOWED_USER_IDS={config['allowed_user_ids']}",
        "",
        "# ── Клиентская конфигурация ────────────────────────────────────",
        f"GIS_DOMAIN={config['gis_domain']}",
        f"CHAT_MONITOR_NICHE_DESCRIPTION={config['niche_description']}",
        f"CHAT_MONITOR_LEAD_DESCRIPTION={config['lead_description']}",
        f"CHAT_MONITOR_OFFER_PRODUCT={config['offer_product']}",
        f"CHAT_MONITOR_KEYWORDS={config['keywords']}",
        f"AI_SERVICE_TYPE={config['ai_service_type']}",
        f"AI_MAIN_OFFER={config['ai_main_offer']}",
        f"AI_RESPONSE_LANGUAGE={config['ai_response_language']}",
        "",
        "# ── Бэкап ──────────────────────────────────────────────────────",
        f"BACKUP_DIR={config['backup_dir']}",
        f"BACKUP_KEEP={config['backup_keep']}",
        "",
    ]

    if config.get("chat_monitor_enabled"):
        lines += [
            "# ── Chat Monitor (Telethon) ────────────────────────────────────",
            f"CHAT_MONITOR_OWNER_TG_ID={config['chat_monitor_owner_tg_id']}",
            f"CHAT_MONITOR_API_ID={config['chat_monitor_api_id']}",
            f"CHAT_MONITOR_API_HASH={config['chat_monitor_api_hash']}",
            f"CHAT_MONITOR_PHONE={config['chat_monitor_phone']}",
            f"CHAT_MONITOR_MIN_SCORE={config['chat_monitor_min_score']}",
            "",
        ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Interactive wizard
# ─────────────────────────────────────────────────────────────────────────────

def _run_wizard() -> dict:
    """Интерактивный мастер настройки. Возвращает словарь конфига."""
    print("\n" + "═" * 60)
    print("  Sales Agent Bot — Мастер настройки нового клиента")
    print("═" * 60)
    print("Отвечай на вопросы. Enter = значение по умолчанию в [скобках].")

    config: dict = {}

    # ── Telegram Bot ──────────────────────────────────────────────────────────
    _section("1. Telegram Bot")
    config["bot_token"] = _ask("BOT_TOKEN (от @BotFather)", required=True)

    # ── LLM ───────────────────────────────────────────────────────────────────
    _section("2. LLM-провайдер")
    print("  Варианты: openrouter, anthropic")
    config["llm_provider"] = _ask("LLM_PROVIDER", default="openrouter")
    config["llm_api_key"] = _ask("LLM_API_KEY", required=True)
    if config["llm_provider"] == "openrouter":
        config["llm_model"] = _ask("LLM_MODEL", default="moonshotai/kimi-k2.6:free")
        config["llm_base_url"] = _ask("LLM_BASE_URL", default="https://openrouter.ai/api/v1")
    else:
        config["llm_model"] = _ask("LLM_MODEL (модель Anthropic)", default="claude-sonnet-4-5")
        config["llm_base_url"] = ""
    config["llm_daily_limit"] = _ask("LLM_DAILY_LIMIT (0 = без лимита)", default="0")

    # ── БД ────────────────────────────────────────────────────────────────────
    _section("3. База данных")
    config["db_url"] = _ask("DB_URL", default="sqlite+aiosqlite:///./sales_agent.db")

    # ── Безопасность ──────────────────────────────────────────────────────────
    _section("4. Безопасность")
    print("  Узнай свой Telegram ID через @userinfobot")
    config["allowed_user_ids"] = _ask("ALLOWED_USER_IDS (через запятую)", default="")

    # ── Клиентская конфигурация ───────────────────────────────────────────────
    _section("5. Клиентская конфигурация (ниша и оффер)")
    print("  Эти параметры определяют под какую нишу настроен бот.")
    config["gis_domain"] = _ask("GIS_DOMAIN", default="2gis.kz")
    config["niche_description"] = _ask(
        "Описание ниши (для LLM)", default="маникюр/ногтевой сервис"
    )
    config["lead_description"] = _ask(
        "Описание целевого лида",
        default="соло-мастер маникюра, который публично упоминает запись клиентов",
    )
    config["offer_product"] = _ask(
        "Наш продукт/оффер", default="сервис записи клиентов через Telegram-бота"
    )
    config["keywords"] = _ask(
        "Ключевые слова Chat Monitor (через запятую, пусто = встроенные)",
        default="",
    )
    config["ai_service_type"] = _ask(
        "Тип услуг для AI-анализа",
        default="digital-услуги (сайт, онлайн-запись, SMM, реклама)",
    )
    config["ai_main_offer"] = _ask("Главный оффер для AI", default="запись через Telegram-бота")
    config["ai_response_language"] = _ask("Язык ответов бота", default="русском")

    # ── Бэкап ─────────────────────────────────────────────────────────────────
    _section("6. Бэкап")
    config["backup_dir"] = _ask("BACKUP_DIR", default="backups")
    config["backup_keep"] = _ask("BACKUP_KEEP (количество копий)", default="14")

    # ── Chat Monitor ──────────────────────────────────────────────────────────
    _section("7. Chat Monitor (Telethon userbot)")
    config["chat_monitor_enabled"] = _ask_bool("Настроить Chat Monitor?", default=False)
    if config["chat_monitor_enabled"]:
        print("  API ID/HASH берутся на https://my.telegram.org/apps")
        config["chat_monitor_owner_tg_id"] = _ask("CHAT_MONITOR_OWNER_TG_ID", required=True)
        config["chat_monitor_api_id"] = _ask("CHAT_MONITOR_API_ID", required=True)
        config["chat_monitor_api_hash"] = _ask("CHAT_MONITOR_API_HASH", required=True)
        config["chat_monitor_phone"] = _ask("CHAT_MONITOR_PHONE (+77001234567)", required=True)
        config["chat_monitor_min_score"] = _ask("CHAT_MONITOR_MIN_SCORE", default="0.7")
    else:
        for key in ("chat_monitor_owner_tg_id", "chat_monitor_api_id",
                    "chat_monitor_api_hash", "chat_monitor_phone", "chat_monitor_min_score"):
            config[key] = ""

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main(output_path: str, non_interactive: bool, env_file: str | None) -> int:
    if non_interactive and env_file:
        # Загружаем существующий .env и только проверяем
        print(f"Проверяем конфиг из {env_file}...")
        os.environ.setdefault("ENV_FILE", env_file)
        # Перезагружаем settings с указанным файлом
        from pydantic_settings import BaseSettings, SettingsConfigDict

        class TempSettings(BaseSettings):
            model_config = SettingsConfigDict(env_file=env_file, env_file_encoding="utf-8", extra="ignore")
            bot_token: str = ""
            db_url: str = "sqlite+aiosqlite:///./sales_agent.db"

        temp = TempSettings()
        bot_token = temp.bot_token
        db_url = temp.db_url
    else:
        config = _run_wizard()
        bot_token = config["bot_token"]
        db_url = config["db_url"]

        # Генерируем .env
        env_content = _generate_env(config)
        output = Path(output_path)
        if output.exists():
            overwrite = _ask_bool(f"\n{output} уже существует. Перезаписать?", default=False)
            if not overwrite:
                print("Отменено.")
                return 1
        output.write_text(env_content, encoding="utf-8")
        if os.name != "nt":
            os.chmod(output, 0o600)
        print(f"\n✅ Файл {output} создан.")

    # ── Проверка Telegram Bot API ─────────────────────────────────────────────
    print("\n🔍 Проверяем подключение к Telegram Bot API...")
    ok, result = await _check_bot_token(bot_token)
    if ok:
        print(f"  ✅ Бот найден: {result}")
    else:
        print(f"  ❌ Ошибка: {result}")
        print("  Проверь BOT_TOKEN и попробуй снова.")
        return 1

    # ── Инициализация БД ──────────────────────────────────────────────────────
    from sqlalchemy.engine.url import make_url

    parsed_url = make_url(db_url)
    safe_db_url = parsed_url.set(password="***") if parsed_url.password else parsed_url
    print(f"\n🗄  Инициализируем БД: {safe_db_url.render_as_string(hide_password=True)}")
    ok, result = await _init_database(db_url)
    if ok:
        print("  ✅ БД готова.")
    else:
        print(f"  ❌ Ошибка инициализации БД: {result}")
        return 1

    # ── Итог ──────────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  ✅ Настройка завершена успешно!")
    print("═" * 60)
    if not non_interactive:
        print("\nСледующие шаги:")
        print(f"  1. Проверь {output_path} и при необходимости отредактируй")
        print("  2. Запусти бота: python bot.py")
        print("  3. Chat Monitor запускается внутри bot.py; отдельный процесс не нужен")
        print("  4. Для автозапуска: см. deploy/README.md")
    return 0


def run() -> None:
    parser = argparse.ArgumentParser(description="Sales Agent Bot — мастер настройки клиента")
    parser.add_argument("--output", default=".env", help="Путь к выходному .env файлу (default: .env)")
    parser.add_argument("--non-interactive", action="store_true", help="Только проверить существующий конфиг")
    parser.add_argument("--env-file", default=None, help="Путь к существующему .env для проверки")
    args = parser.parse_args()

    exit_code = asyncio.run(main(args.output, args.non_interactive, args.env_file))
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
