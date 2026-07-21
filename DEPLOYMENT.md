# Deployment Guide

Актуальная production-схема: один процесс `bot.py`, PostgreSQL, Redis с паролем,
Alembic migrations до старта и обязательная incident response перед rollout.

## 📋 Предварительные требования

- Docker и Docker Compose (рекомендуется)
- PostgreSQL 16+
- Redis 7+ с паролем
- Telegram Bot Token от @BotFather
- LLM API Key (Anthropic или OpenRouter)

## Критический блокер

Не запускайте production до завершения шагов из `SECURITY_INCIDENT.md`:

1. Ротация `BOT_TOKEN`.
2. Ротация LLM API key.
3. Завершение всех Telegram sessions сервисного аккаунта.
4. Создание новой Telethon session.
5. Очистка Git history через `git filter-repo` и force-push по согласованию.
6. Заполнение `SECRETS_ROTATED_AT` фактическим ISO-8601 временем.

---

## 🐳 Деплой через Docker (рекомендуется)

### Вариант 1: Docker Compose

**1. Клонировать репозиторий:**
```bash
git clone <repo-url>
cd sales_agent_bot
```

**2. Создать .env файл:**
```bash
cp .env.example .env
nano .env  # или vim, или любой редактор
```

**Минимальная production-конфигурация `.env`:**
```env
BOT_TOKEN=your_bot_token_from_botfather
ENVIRONMENT=production
SECRETS_ROTATED_AT=2026-07-21T12:00:00Z
ALLOWED_USER_IDS=123456789

# PostgreSQL + Redis обязательны в production
POSTGRES_PASSWORD=replace_me
REDIS_PASSWORD=replace_me
DB_URL=postgresql+asyncpg://sales_agent:replace_me@postgres:5432/sales_agent
REDIS_URL=redis://:replace_me@redis:6379/0
AUTO_CREATE_SCHEMA=false

# LLM
LLM_PROVIDER=openrouter
LLM_MODEL=moonshotai/kimi-k2.6:free
LLM_API_KEY=your_openrouter_api_key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_ALLOWED_HOSTS=openrouter.ai
LLM_DAILY_LIMIT=100

PII_ENCRYPTION_KEY=replace_me
BACKUP_ENCRYPTION_KEY=replace_me_different
```

**3. Проверить production Compose-конфигурацию:**
```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres config --quiet
```

Или выполнить весь fail-closed flow одной командой:

```bash
bash scripts/deploy_production.sh
```

Windows PowerShell:

```powershell
.\scripts\deploy_production.ps1
```

**4. Накатить миграции:**
```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres run --rm migrate
```

**5. Проверить readiness:**
```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres run --rm bot python -m scripts.production_readiness
```

**6. Запустить сервисы:**
```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres up -d postgres redis bot
docker compose -f docker-compose.yml -f docker-compose.production.yml logs -f bot
```

**7. Выполнить backup/restore smoke test:**

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres --profile backup run --rm backup
docker compose -f docker-compose.yml -f docker-compose.production.yml run --rm bot python -m scripts.decrypt_backup /app/backups/<file>.sql.enc /tmp/restore.sql
# Восстановить /tmp/restore.sql в отдельную disposable PostgreSQL database
# и выполнить миграционный/CRUD smoke test. Не восстанавливать поверх production DB.
```

Для SQLite backup используйте `python -m scripts.verify_backup <backup.db>`;
этот verifier не предназначен для PostgreSQL SQL dumps.

---

### Вариант 2: Docker без Compose

Этот вариант подходит только для development/staging. Для production используйте
Compose-схему выше, потому что она явно связывает bot, PostgreSQL, Redis,
migrate и backup volumes.

**1. Создать volume для данных:**
```bash
docker volume create sales-bot-data
```

**2. (Опционально) Запустить Redis:**
```bash
docker run -d \
  --name sales-bot-redis \
  --restart unless-stopped \
  redis:7-alpine
```

**3. Собрать образ:**
```bash
docker build -t sales-agent-bot .
```

**4. Запустить бота:**
```bash
docker run -d \
  --name sales-bot \
  --restart unless-stopped \
  --env-file .env \
  --link sales-bot-redis:redis \
  -e REDIS_URL=redis://redis:6379/0 \
  -v sales-bot-data:/app/data \
  sales-agent-bot
```

**5. Проверить:**
```bash
docker ps
docker logs -f sales-bot
docker exec sales-bot python scripts/healthcheck.py
```

---

## 🖥️ Деплой на VPS (без Docker)

### Ubuntu/Debian

**1. Установить зависимости системы:**
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip redis-server
```

**2. Создать пользователя для бота:**
```bash
sudo useradd -m -s /bin/bash botuser
sudo su - botuser
```

**3. Клонировать и настроить:**
```bash
git clone <repo-url>
cd sales_agent_bot

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-lock.txt

cp .env.example .env
nano .env  # настроить BOT_TOKEN, LLM_API_KEY, REDIS_URL
```

**4. Проверить запуск:**
```bash
python bot.py
# Ctrl+C для остановки
```

**5. Создать systemd service:**
```bash
# Вернуться к root
exit

# Создать service файл
sudo nano /etc/systemd/system/sales-bot.service
```

**Содержимое sales-bot.service:**
```ini
[Unit]
Description=AI Sales Agent Telegram Bot
After=network.target redis.service

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/sales_agent_bot
Environment="PATH=/home/botuser/sales_agent_bot/venv/bin"
ExecStart=/home/botuser/sales_agent_bot/venv/bin/python bot.py
Restart=always
RestartSec=10

# Лимиты
LimitNOFILE=65535

# Логирование
StandardOutput=append:/var/log/sales-bot.log
StandardError=append:/var/log/sales-bot-error.log

[Install]
WantedBy=multi-user.target
```

**6. Запустить и включить автозапуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl start sales-bot
sudo systemctl enable sales-bot

# Проверить статус
sudo systemctl status sales-bot

# Просмотр логов
sudo journalctl -u sales-bot -f
# или
sudo tail -f /var/log/sales-bot.log
```

**7. Управление:**
```bash
sudo systemctl restart sales-bot  # Перезапуск
sudo systemctl stop sales-bot     # Остановка
sudo systemctl start sales-bot    # Запуск
```

---

## ☁️ Деплой в облако

### Digital Ocean / AWS / GCP

**1. Создать VM (Droplet/EC2/Compute Engine):**
- OS: Ubuntu 22.04 LTS
- RAM: минимум 512 MB (рекомендуется 1 GB)
- CPU: 1 core
- Storage: 10 GB

**2. Установить Docker:**
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

**3. Установить Docker Compose:**
```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

**4. Клонировать и запустить:**
```bash
git clone <repo-url>
cd sales_agent_bot
cp .env.example .env
nano .env  # настроить

docker-compose up -d bot
```

**5. Настроить firewall (опционально):**
```bash
# Только SSH (бот работает через Telegram API, входящие порты не нужны)
sudo ufw allow 22/tcp
sudo ufw enable
```

---

### Heroku

**⚠️ Внимание:** Heroku не подходит для этого бота из-за:
- Ephemeral filesystem (SQLite будет теряться)
- Платная dyno для непрерывной работы

Используйте PostgreSQL addon или другую платформу.

---

### Railway / Render / Fly.io

**1. Создать аккаунт на платформе**

**2. Подключить GitHub репозиторий**

**3. Настроить переменные окружения:**
- `BOT_TOKEN`
- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`
- `DB_URL` (использовать PostgreSQL addon)
- `REDIS_URL` (использовать Redis addon)

**4. Настроить deployment:**
- Build command: `pip install -r requirements-lock.txt`
- Start command: `python bot.py`

**5. Добавить Health Check:**
- Path: не требуется (polling mode)
- Command: `python scripts/healthcheck.py`

---

## 🔄 Обновление развернутого бота

### Docker Compose

```bash
cd sales_agent_bot

# Получить новую версию
git pull

# Пересобрать и перезапустить
docker-compose build bot
docker-compose up -d bot

# Проверить логи
docker-compose logs -f bot
```

### Systemd

```bash
sudo su - botuser
cd sales_agent_bot

# Получить новую версию
git pull

# Обновить зависимости
source venv/bin/activate
pip install -r requirements-lock.txt

# Перезапустить
exit
sudo systemctl restart sales-bot
sudo systemctl status sales-bot
```

---

## 🔐 Безопасность в production

### 1. Защита .env файла

```bash
# Права доступа только для владельца
chmod 600 .env

# Проверить, что .env в .gitignore
grep "^\.env$" .gitignore
```

### 2. Регулярные бэкапы

**Автоматический бэкап (cron):**
```bash
# Добавить в crontab
crontab -e

# Бэкап каждый день в 3:00
0 3 * * * cd /home/botuser/sales_agent_bot && /home/botuser/sales_agent_bot/venv/bin/python scripts/backup_db.py

# Или через docker compose
0 3 * * * cd /home/botuser/sales_agent_bot && docker compose -f docker-compose.yml -f docker-compose.production.yml --profile postgres --profile backup run --rm backup
```

### 3. Мониторинг

**Uptime мониторинг (UptimeRobot/Healthchecks.io):**
```bash
# Создать скрипт для HTTP healthcheck
# /home/botuser/healthcheck.sh
#!/bin/bash
cd /home/botuser/sales_agent_bot
source venv/bin/activate
python scripts/healthcheck.py
exit $?
```

**Настроить webhook на Healthchecks.io:**
```bash
# В crontab
*/5 * * * * /home/botuser/healthcheck.sh && curl -fsS --retry 3 https://hc-ping.com/your-uuid > /dev/null
```

### 4. Логирование

**Ротация логов (logrotate):**
```bash
sudo nano /etc/logrotate.d/sales-bot
```

```
/var/log/sales-bot*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 botuser botuser
}
```

---

## 📊 Мониторинг production

### Проверка состояния

```bash
# Healthcheck
docker exec sales-bot python scripts/healthcheck.py

# Статистика через бота
# Отправить /health в Telegram

# Redis
redis-cli -a "$REDIS_PASSWORD" INFO stats

# Readiness
python -m scripts.production_readiness
```

### Алерты

**Telegram уведомления при падении:**

1. Создать отдельного бота для мониторинга (@BotFather)
2. Создать скрипт `/home/botuser/alert.sh`:
```bash
#!/bin/bash
BOT_TOKEN="monitoring_bot_token"
CHAT_ID="your_chat_id"
MESSAGE="🚨 Sales Bot is DOWN!"

if ! systemctl is-active --quiet sales-bot; then
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$MESSAGE"
fi
```

3. Добавить в crontab:
```bash
*/5 * * * * /home/botuser/alert.sh
```

---

## 🐛 Troubleshooting в production

### Бот не запускается после обновления

```bash
# Проверить логи
docker-compose logs bot
# или
sudo journalctl -u sales-bot -n 100

# Проверить конфиг
docker-compose exec bot python scripts/healthcheck.py

# Откатиться на предыдущую версию
git log --oneline
git checkout <previous-commit>
docker-compose up -d bot
```

### Высокое использование памяти

```bash
# Проверить использование
docker stats sales-bot

# Добавить memory limit в docker-compose.yml
services:
  bot:
    mem_limit: 512m
    memswap_limit: 512m
```

### Проблемы с Redis

```bash
# Проверить connection
redis-cli -h localhost -p 6379 ping

# Посмотреть ключи FSM
redis-cli -h localhost -p 6379 KEYS "fsm:*"

# Очистить FSM (при проблемах)
redis-cli -h localhost -p 6379 FLUSHDB
```

### База данных заблокирована (SQLite)

```bash
# Проверить locks
lsof /app/data/sales_agent.db

# Перезапустить бота
docker-compose restart bot

# Если не помогает - миграция на PostgreSQL
```

---

## 📚 Дополнительные ресурсы

- [README.md](README.md) — основная документация
- [FIXES_APPLIED.md](FIXES_APPLIED.md) — исправленные проблемы
- [Docker Hub Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [systemd Service Documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)

---

## ✅ Чеклист готовности к production

- [ ] Утёкшие токены и Telegram sessions ротированы
- [ ] `SECRETS_ROTATED_AT` заполнен фактическим временем ротации
- [ ] История Git очищена от архивов, старые клоны отозваны
- [ ] `DB_URL` указывает на PostgreSQL
- [ ] `REDIS_URL` настроен с паролем и доступен
- [ ] `ALLOWED_USER_IDS` непуст
- [ ] `LLM_DAILY_LIMIT > 0`
- [ ] `PII_ENCRYPTION_KEY` и отдельный `BACKUP_ENCRYPTION_KEY` заданы
- [ ] `AUTO_CREATE_SCHEMA=false`
- [ ] `docker compose --profile postgres run --rm migrate` выполнен
- [ ] `python -m scripts.production_readiness` проходит
- [ ] Backup/restore smoke test выполнен
- [ ] `/health` и основные сценарии вручную проверены
