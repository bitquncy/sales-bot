# TODO: Исправление sales_agent_bot

## Шаг 1 — Git: закоммитить и запуштить staged изменения
- [x] Проанализировать состояние Git
- [x] Закоммитить staged changes
- [x] Merge с origin/main (--allow-unrelated-histories)
- [x] Запушить на origin (bitquncy/sales-bot) ✅

## Шаг 2 — Git: удалить лишний remote (github/project-not-broyk)
- [ ] git remote remove github

## Шаг 3 — Создать .env.example в репозитории
- [ ] Создать .env.example с шаблоном всех переменных

## Шаг 4 — Исправить Chat Monitor для запуска на Render
- [ ] Отключить Chat Monitor в production конфиге (или настроить QR-логин)

## Шаг 5 — Настроить production-конфиг для Render (PostgreSQL + Redis)
- [ ] Обновить .env для Render
- [ ] Настроить PostgreSQL
- [ ] Настроить Redis

## Шаг 6 — Исправить TelegramConflictError
- [ ] Остановить дублирующиеся инстансы бота

