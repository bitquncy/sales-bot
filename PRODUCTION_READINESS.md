# Production Readiness

## Executive Summary

Статус проекта после аудита: кодовая база близка к production-ready по архитектуре,
безопасности и тестируемости, но репозиторий всё ещё не готов к реальному rollout,
пока не завершены incident-response шаги и не удалены утёкшие архивы из Git history.

Предварительный вердикт: `NOT READY FOR PRODUCTION`.

## Architecture

- Основная точка входа: `bot.py`.
- Runtime-модель: один aiogram polling process.
- Дополнительные фоновые задачи: reminders, retention cleanup, embedded Chat Monitor.
- Persistence: async SQLAlchemy, SQLite для development, PostgreSQL для production.
- Coordination: Redis для FSM, distributed locks, rate limit и кэша.
- External integrations: Telegram Bot API, Telethon, Overpass API, Anthropic/OpenAI-compatible LLM, Sentry.
- Deployment: Docker/Docker Compose и systemd units.

## Critical Issues

1. В Git index/history присутствуют запрещённые архивы с runtime-данными.
   - Тип: security incident / secret exposure.
   - Файлы: `project.zip`, `chat_monitor_changes.zip`, `chat_monitor_bot_settings_changes.zip`, `qa_fixes_changes.zip`.
   - Статус: кодовые guard'ы исправлены, но репозиторий всё ещё требует cleanup history и нового чистого commit state.

2. Production secrets считаются скомпрометированными.
   - Тип: `BOT_TOKEN`, LLM API key, Telethon session, локальная CRM data exposure.
   - Также был обнаружен локальный `.claude/settings.json` с Anthropic-compatible token; файл удалён и `.claude/` добавлен в ignore.
   - Статус: требуется ручная ротация и новая Telethon session.

3. Production rollout нельзя считать завершённым без PostgreSQL/Redis readiness и миграций.
   - Статус: код и проверки есть, но это нужно выполнить на реальном целевом окружении.

4. Внешние API должны переживать кратковременные 429/5xx/network failures.
   - Исправлено: добавлены bounded retries, exponential backoff и поддержка `Retry-After` для LLM, Overpass и прямого Bot API клиента.

## High Priority Issues

1. `scripts/healthcheck.py` раньше не проверял readiness PostgreSQL schema и Redis.
   - Исправлено: healthcheck теперь валидирует schema readiness и Redis availability.

2. `deploy/install.sh` оставался несогласованным с текущей архитектурой.
   - Исправлено: удалён legacy install path для standalone `sales-chat-monitor.service`.

3. `scripts/check_tracked_secrets.py` раньше не ловил уже удалённые из дерева, но всё ещё tracked файлы.
   - Исправлено: guard теперь проверяет Git index независимо от наличия файла в рабочем дереве.

## Medium Priority Issues

1. В репозитории отсутствуют `railway.json`, `nixpacks.toml`, `Procfile`, `runtime.txt`, `pyproject.toml`.
   - Вывод: Railway/Nixpacks deployment в текущем состоянии не настроен; authoritative deployment path сейчас Docker/systemd.

2. Mypy в CI non-blocking.
   - Риск: часть типовых регрессий может пройти CI.

3. Docker build занимает заметное время из-за системных пакетов и полного lock install.
   - Риск умеренный, содержательной ошибки в Dockerfile аудит не выявил.

## Low Priority Issues

1. В репозитории много исторических/внутренних markdown-отчётов, часть из них противоречит текущему состоянию.
2. В рабочем дереве встречаются локальные артефакты (`.claude`, `.kimchi`, runtime files), требующие дисциплины перед публикацией.

## Security Audit

- Fail-closed production config внедрён.
- Production требует:
  - `ENVIRONMENT=production`
  - PostgreSQL
  - Redis
  - непустой `ALLOWED_USER_IDS`
  - `LLM_DAILY_LIMIT > 0`
  - `PII_ENCRYPTION_KEY`
  - отдельный `BACKUP_ENCRYPTION_KEY`
  - `AUTO_CREATE_SCHEMA=false`
  - `SECRETS_ROTATED_AT`
- Prompt injection hardening есть.
- PII encryption и retention есть.
- Sentry scrubber и user hashing есть.
- `check_tracked_secrets` усилен.
- Внешние retry policies bounded и не повторяют постоянные 4xx или невалидные ответы.
- История Git всё ещё содержит следы инцидента: production запуск блокирован до cleanup.

## Database Audit

- Async SQLAlchemy configured.
- SQLite hardened for development: WAL, foreign keys, busy timeout, `BEGIN IMMEDIATE`.
- PostgreSQL path поддержан для production.
- Alembic migrations присутствуют (`0001`-`0006`).
- `verify_schema()` используется для fail-fast startup/readiness.
- Repo layer содержит owner-safe quota, reminder claiming, inbox claiming и audit log.
- Критичных необработанных race condition в проверенных сценариях не обнаружено.

## Deployment Audit

- Главный deployment path: `Dockerfile` + `docker-compose.yml`.
- Secondary path: systemd через `deploy/`.
- Railway/Nixpacks/Procfile/runtime config отсутствуют, значит это не рабочий deployment target на текущий момент.
- `docker-compose.yml` теперь требует явные `POSTGRES_PASSWORD` и `REDIS_PASSWORD` для production-profile.
- `docker-compose.production.yml` добавляет health-gated startup dependencies: PostgreSQL/Redis перед migrate/bot.
- `scripts/deploy_production.sh` и `scripts/deploy_production.ps1` автоматизируют fail-closed rollout без вывода секретов.
- SQLite backup restore проверяется через `scripts.verify_backup`; PostgreSQL SQL dump нужно восстановить в отдельную disposable PostgreSQL database.
- Embedded Chat Monitor задокументирован как единственный production-safe режим.

## Test Results

Последняя локальная верификация:

- `pytest -q`: `328 passed`
- `tests/test_ops_guards.py` + `tests/test_production_hardening.py`: `9 passed`
- `ruff check . --exclude alembic`: passed
- `pip_audit -r requirements-lock.txt`: `No known vulnerabilities found`
- `pip install --dry-run --require-hashes -r requirements-lock.txt`: passed
- Retry regression tests: 61 passed in targeted run
- Safe live smoke runner добавлен: `python -m scripts.live_smoke`.
- Safe local live smoke: database-only check passed.

Coverage:

- CI запускает `pytest -v --cov=. --cov-report=term-missing`
- локально финальный coverage report в этой сессии отдельно не снимался.

## Docker Status

- `docker build -t sales-agent-bot-audit .`: passed from scratch.
- Container runtime imports passed.
- Container database-only live smoke passed.
- Image runs as non-root `appuser` and has the configured Bot API healthcheck.
- `docker compose --profile postgres config --quiet` проходит при заданных `POSTGRES_PASSWORD` и `REDIS_PASSWORD`.

## Production Checklist

- [ ] Ротировать `BOT_TOKEN`
- [ ] Ротировать LLM API key
- [ ] Завершить все Telegram sessions service account
- [ ] Создать новую Telethon session
- [ ] Очистить Git history (`git filter-repo`) и force-push по согласованию
- [ ] Удалить/отозвать старые клоны, artifacts, releases, caches
- [ ] Заполнить production `.env` новыми секретами
- [ ] Установить `SECRETS_ROTATED_AT`
- [ ] Проверить `ALLOWED_USER_IDS`
- [ ] Установить `DB_URL` на PostgreSQL
- [ ] Установить `REDIS_URL` с паролем
- [ ] Установить `PII_ENCRYPTION_KEY`
- [ ] Установить отдельный `BACKUP_ENCRYPTION_KEY`
- [ ] Выполнить `docker compose --profile postgres run --rm migrate`
- [ ] Выполнить `python -m scripts.production_readiness`
- [ ] Выполнить backup/restore smoke test
- [ ] Для SQLite выполнить `python -m scripts.verify_backup` для восстановленного backup
- [ ] Для PostgreSQL восстановить SQL dump в отдельную disposable database и выполнить smoke test
- [ ] Проверить `/health` и основной user flow вручную
- [ ] Выполнить `python -m scripts.live_smoke` после ротации секретов

## Remaining Risks

1. История Git уже утекла и не может быть исправлена только изменением рабочего дерева.
2. Реальный production PostgreSQL/Redis stack не был полностью поднят и прогнан end-to-end в этой локальной сессии.
3. Railway deployment path отсутствует как рабочая конфигурация.
4. Mypy пока не является blocking gate в CI.
5. Локальный `.env` остаётся development-файлом с прежними credentials и должен быть заменён до запуска.

## Final Verdict

`NOT READY FOR PRODUCTION`

Причина: остались не кодовые, но критичные security/deployment blockers: историческая утечка секретов, tracked архивы в Git, обязательная ручная ротация и необходимость завершить production readiness на реальном окружении.
