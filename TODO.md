# TODO: Исправление sales_agent_bot

## ✅ Шаг 1 — Git: закоммитить и запуштить staged изменения
- [x] Проанализировать состояние Git
- [x] Закоммитить staged changes
- [x] Merge с origin/main (--allow-unrelated-histories)
- [x] Запушить на origin (bitquncy/sales-bot)

## ✅ Шаг 2 — Git: удалить лишний remote (github/project-not-broyk)
- [x] git remote remove github

## ✅ Шаг 3 — .env.example
- [x] Проверен — существует с полной документацией

## ✅ Шаг 4 — Исправить Chat Monitor для запуска на Render
- [x] Добавлена проверка наличия .session файла перед авторизацией
- [x] Добавлен человекочитаемый error handling для EOFError
- [x] Изменения закоммичены и запушены

## ✅ Шаг 5 — Очистка Git истории от секретов (Security Incident)
- [x] Установлен git-filter-repo
- [x] Удалены из истории: project.zip, chat_monitor_*.zip, qa_fixes_changes.zip
- [x] Force push на origin выполнен
- ⚠️ **Нужно:** Сменить BOT_TOKEN в BotFather, LLM_API_KEY, создать новую Telethon-сессию

## ✅ Шаг 6 — Проверка функциональности
- [x] Healthcheck пройден — бот отвечает, БД работает
- [x] **333 теста пройдены** — 100% успех!
- [x] TelegramConflictError resolved — временный конфликт при деплое (старый инстанс выключается)
- [x] Chat Monitor падает чисто без краша бота

## 🔴 Шаг 7 — Настроить production-конфиг для Render (ваши действия)
1. **Остановите локальный бот** (если запущен)
2. Пересоздайте **Telethon-сессию локально**: `python scripts/telethon_qr_login.py`
3. Загрузите `.session` файл на Render как secret file
4. **Смените секреты (обязательно):**
   - `BOT_TOKEN` в @BotFather
   - `LLM_API_KEY` / `ANTHROPIC_API_KEY`
5. На Render добавьте в Environment:
   - `ENVIRONMENT=production`
   - `AUTO_CREATE_SCHEMA=false`
   - `ALLOWED_USER_IDS=<ваш_id>`
   - `LLM_DAILY_LIMIT=100`
   - `PII_ENCRYPTION_KEY` (сгенерировать)
   - `BACKUP_ENCRYPTION_KEY` (другой ключ)
   - `SECRETS_ROTATED_AT=2026-07-23T06:00:00Z`
6. Добавьте PostgreSQL и Redis addon'ы
7. Выполните `alembic upgrade head`
