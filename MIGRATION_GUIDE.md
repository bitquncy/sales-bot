# Migration Guide: v1.x → v2.0.0

Руководство по обновлению до версии 2.0.0 с критическими исправлениями безопасности.

## 🎯 Что изменилось

### Новые возможности
- ✅ Redis поддержка для FSM storage
- ✅ Distributed idempotency locks
- ✅ Global error handler
- ✅ Rate limiting middleware
- ✅ Healthcheck endpoint
- ✅ Graceful shutdown

### Breaking Changes
**❌ НЕТ breaking changes** — версия 2.0.0 полностью обратно совместима с 1.x

### Новые зависимости
- `redis>=5.2.1` (опционально, но рекомендуется)

---

## 🚀 Быстрая миграция (5 минут)

### Шаг 1: Остановить бота

**Docker:**
```bash
docker-compose down
```

**Systemd:**
```bash
sudo systemctl stop sales-bot
```

**Локально (Ctrl+C или):**
```bash
pkill -f "python bot.py"
```

### Шаг 2: Создать бэкап (важно!)

```bash
# Бэкап БД
cp sales_agent.db sales_agent.db.backup_$(date +%Y%m%d_%H%M%S)

# Бэкап .env
cp .env .env.backup

# Или использовать встроенный скрипт
python scripts/backup_db.py
```

### Шаг 3: Получить новую версию

```bash
# Сохранить локальные изменения (если есть)
git stash

# Получить обновление
git pull origin main

# Применить локальные изменения обратно (если были)
git stash pop
```

### Шаг 4: Обновить зависимости

**Docker:**
```bash
# Пересобрать образ
docker-compose build bot
```

**Локально:**
```bash
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements-lock.txt
```

### Шаг 5: Обновить .env (опционально)

Добавить новые переменные в `.env`:

```env
# Redis для FSM persistence (опционально, но рекомендуется)
REDIS_URL=redis://localhost:6379/0

# Или оставить пустым для memory storage (как раньше)
# REDIS_URL=
```

**Важно:** Если не добавите REDIS_URL, бот будет работать как раньше (MemoryStorage).

### Шаг 6: Запустить бота

**Docker:**
```bash
docker-compose up -d bot
```

**Systemd:**
```bash
sudo systemctl start sales-bot
```

**Локально:**
```bash
python bot.py
```

### Шаг 7: Проверить работу

**Проверка 1: Логи**
```bash
# Docker
docker-compose logs -f bot

# Systemd
sudo journalctl -u sales-bot -f

# Локально - смотрите stdout
```

Должны увидеть:
```
[INFO] ... Bot started (polling)
[INFO] ... FSM storage: Memory (потеря состояний при рестарте)
# или
[INFO] ... FSM storage: Redis (persistent)
```

**Проверка 2: Healthcheck**
```bash
# В боте отправить команду
/health

# Или через скрипт
python scripts/healthcheck.py
```

**Проверка 3: Основной функционал**
```
/start → Главное меню должно открыться
/stats → Статистика должна показаться
Поиск → Должен работать как раньше
```

---

## 🐳 Миграция с установкой Redis (рекомендуется)

### Docker (самый простой)

**1. Обновить docker-compose.yml**

Добавить Redis service (если ещё не добавлен):
```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 3s
      retries: 3

volumes:
  redis_data:  # Добавить в конец файла
```

**2. Обновить .env**
```env
REDIS_URL=redis://redis:6379/0
```

**3. Запустить Redis и бота**
```bash
docker-compose up -d redis
docker-compose up -d bot
```

**4. Проверить Redis connection**
```bash
docker-compose exec bot python -c "
from redis.asyncio import Redis
import asyncio
async def test():
    r = Redis.from_url('redis://redis:6379/0')
    print('Redis PING:', await r.ping())
asyncio.run(test())
"
```

### Локально (Ubuntu/Debian)

**1. Установить Redis**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

**2. Проверить Redis**
```bash
redis-cli ping
# Должно вернуть: PONG
```

**3. Обновить .env**
```env
REDIS_URL=redis://localhost:6379/0
```

**4. Перезапустить бота**
```bash
sudo systemctl restart sales-bot
```

### Локально (Windows)

**1. Скачать Redis for Windows**
- [Redis для Windows (Memurai)](https://www.memurai.com/)
- Или использовать WSL2 с Redis

**2. Установить и запустить**

**3. Обновить .env**
```env
REDIS_URL=redis://localhost:6379/0
```

**4. Перезапустить бота**

---

## 🔄 Откат на предыдущую версию (если что-то пошло не так)

### Шаг 1: Остановить бота
```bash
docker-compose down
# или
sudo systemctl stop sales-bot
```

### Шаг 2: Восстановить код
```bash
git log --oneline -10  # Найти commit предыдущей версии
git checkout <commit-hash>
```

### Шаг 3: Восстановить БД (если повреждена)
```bash
cp sales_agent.db.backup_YYYYMMDD_HHMMSS sales_agent.db
```

### Шаг 4: Откатить зависимости
```bash
pip install -r requirements-lock.txt
# или
docker-compose build bot
```

### Шаг 5: Запустить старую версию
```bash
docker-compose up -d bot
# или
sudo systemctl start sales-bot
```

---

## ⚙️ Настройка новых возможностей

### Rate Limiting

**Уже включен по умолчанию:**
- 1 сообщение/сек на пользователя
- 2 callback/сек на пользователя

**Изменить лимиты** (в `utils/rate_limit.py`):
```python
MESSAGE_RATE_LIMIT = 2  # секунды между сообщениями
CALLBACK_RATE_LIMIT = 1  # секунды между callback
```

### Access Control

**Ограничить доступ к боту** (в `.env`):
```env
# Comma-separated Telegram user IDs
ALLOWED_USER_IDS=123456789,987654321
```

Узнать свой ID: отправить сообщение @userinfobot

### LLM Daily Limit

**Установить дневной лимит** (в `.env`):
```env
# 0 = без лимита (как раньше)
LLM_DAILY_LIMIT=100
```

---

## 📊 Проверка улучшений после миграции

### 1. FSM Persistence (с Redis)

**Тест:**
1. Начать поиск (/start → Поиск компаний)
2. Ввести город
3. Остановить бота (`docker-compose restart bot`)
4. Бот перезапустится
5. Отправить любое сообщение

**Ожидаемый результат:**
- **С Redis:** FSM состояние сохранилось, бот продолжает с того же места
- **Без Redis:** FSM сброшен, показывается главное меню

### 2. Error Handler

**Тест:**
1. Попытаться сгенерировать сообщение для лида без анализа
2. Или любое действие, которое может вызвать ошибку

**Ожидаемый результат:**
- Вместо краха бота — user-friendly сообщение об ошибке
- FSM состояние сохраняется
- Бот продолжает работать

### 3. Idempotency

**Тест:**
1. Нажать кнопку "Анализ" на лиде
2. Быстро нажать ещё раз (пока первый анализ идёт)

**Ожидаемый результат:**
- Второй клик показывает "Анализ уже выполняется"
- Только один LLM-вызов
- Нет дублей в БД

### 4. Healthcheck

**Тест:**
```bash
# Команда в боте
/health

# Или скрипт
python scripts/healthcheck.py
```

**Ожидаемый результат:**
```
✅ Health Check

Uptime: Xч Yм
База данных: ✅ OK
  • LLM вызовов сегодня: Z
Redis: ✅ Connected  (или "Not configured")
LLM Provider: openrouter
Timestamp (UTC): 2026-07-18 12:34:56
```

---

## 🆘 Частые проблемы при миграции

### Проблема 1: "Module 'redis' not found"

**Решение:**
```bash
pip install redis
# или
pip install -r requirements-lock.txt
```

### Проблема 2: "Redis connection failed"

**Если Redis не нужен:**
```env
# Убрать или закомментировать в .env
# REDIS_URL=
```

**Если нужен:**
```bash
# Проверить Redis
redis-cli ping
docker ps | grep redis
```

### Проблема 3: "FSM storage: Memory" вместо "Redis"

**Причины:**
1. REDIS_URL не задан в .env
2. Redis недоступен (проверить: `redis-cli ping`)
3. Неверный формат REDIS_URL

**Проверка:**
```bash
# В боте
/health

# Смотреть строку "Redis:"
```

### Проблема 4: БД locked после миграции

**Решение:**
```bash
# Перезапустить бота
docker-compose restart bot

# Или проверить процессы
lsof sales_agent.db
```

### Проблема 5: Старые FSM состояния "висят"

**С Redis:**
```bash
# Очистить FSM ключи
redis-cli KEYS "fsm:*" | xargs redis-cli DEL
```

**Без Redis:**
```bash
# Перезапустить бота
docker-compose restart bot
```

---

## ✅ Чеклист миграции

- [ ] Создан бэкап БД
- [ ] Создан бэкап .env
- [ ] Получена новая версия (git pull)
- [ ] Обновлены зависимости (pip install / docker build)
- [ ] Добавлен REDIS_URL в .env (опционально)
- [ ] Бот запущен без ошибок
- [ ] Проверены логи (нет ERROR)
- [ ] Выполнен /health (показывает OK)
- [ ] Выполнен /stats (показывает данные)
- [ ] Основной функционал работает (поиск, CRM)
- [ ] FSM persistence работает (если Redis)

---

## 📚 Дополнительная информация

- [FIXES_APPLIED.md](FIXES_APPLIED.md) — полный список изменений
- [README.md](README.md) — обновлённая документация
- [DEPLOYMENT.md](DEPLOYMENT.md) — инструкции по деплою

---

**Миграция завершена! 🎉**

Если возникли проблемы — смотри секцию "Откат на предыдущую версию" выше.
