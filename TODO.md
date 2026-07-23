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

## 🔴 Шаг 6 — TelegramConflictError (дублирование бота)
**Требует действий на Render:**
1. Остановить локальный экземпляр бота (Ctrl+C)
2. На Render: Dashboard → Manual Deploy → Deploy latest commit
3. Убедиться, что только один инстанс активен

## 🔴 Шаг 7 — Настроить production-конфиг для Render
**Требует действий на Render:**
1. Добавить PostgreSQL addon в Render Dashboard
2. Добавить Redis addon в Render Dashboard
3. Обновить переменные окружения в Render:
   - `ENVIRONMENT=production`
   - `DB_URL=postgresql+asyncpg://...`
   - `REDIS_URL=redis://...`
   - `AUTO_CREATE_SCHEMA=false`
   - `ALLOWED_USER_IDS=<ваш_telegram_id>`
   - `PII_ENCRYPTION_KEY=<сгенерировать>`
   - `BACKUP_ENCRYPTION_KEY=<сгенерировать>`
   - `LLM_DAILY_LIMIT=100`
   - `SECRETS_ROTATED_AT=<время_ротации>`
4. Выполнить `alembic upgrade head` (через Run → Shell на Render)
