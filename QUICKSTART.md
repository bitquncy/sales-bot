# Quick Start Guide

Быстрый старт проекта за 5 минут.

---

## 🚀 За 5 минут (Docker)

### 1. Предварительные требования

- Docker и Docker Compose
- Telegram Bot Token (получить у @BotFather)
- LLM API Key (OpenRouter или Anthropic)

### 2. Клонировать проект

```bash
git clone <repo-url>
cd sales_agent_bot
```

### 3. Настроить .env

```bash
cp .env.example .env
```

**Отредактировать .env** (минимальная конфигурация):

```env
# Telegram
BOT_TOKEN=123456:ABCdefGHIjklMNOpqrsTUVwxyz  # от @BotFather

# LLM (бесплатный вариант - OpenRouter)
LLM_PROVIDER=openrouter
LLM_MODEL=moonshotai/kimi-k2.6:free
LLM_API_KEY=your_api_key_here  # с https://openrouter.ai/
LLM_BASE_URL=https://openrouter.ai/api/v1
```

### 4. Запустить

```bash
docker-compose up -d bot
```

### 5. Проверить

```bash
# Статус контейнера (должен быть "healthy" через 30 сек)
docker ps

# Логи
docker-compose logs -f bot
```

### 6. Использовать

Открыть бота в Telegram и отправить `/start` 🎉

**Если настроен Chat Monitor** (опционально):
- При первом запуске Telethon попросит код авторизации
- Код обычно приходит в официальный Telegram app (не SMS)
- После ввода кода Chat Monitor запустится автоматически
- Логи отображаются вместе с логами бота

---

## 💻 За 10 минут (локально)

### 1. Требования

- Python 3.11+
- Git

### 2. Установка

```bash
# Клонировать
git clone <repo-url>
cd sales_agent_bot

# Создать venv
python3.11 -m venv venv

# Активировать
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Установить зависимости
pip install -r requirements-lock.txt
```

### 3. Настроить

```bash
cp .env.example .env
nano .env  # или любой редактор
```

**Минимальная конфигурация:**
```env
BOT_TOKEN=your_bot_token
LLM_PROVIDER=openrouter
LLM_MODEL=moonshotai/kimi-k2.6:free
LLM_API_KEY=your_openrouter_key
```

### 4. Запустить

```bash
python bot.py
```

### 5. Проверить

- Логи выводятся в консоль
- Отправить `/start` боту в Telegram

### 6. Остановить

```
Ctrl+C
```

---

## 🎯 Первые шаги

### Основные команды

```
/start - открыть главное меню
/help - справка по боту
/stats - статистика лидов
/health - проверка состояния
/cancel - отменить текущее действие
```

### Базовый flow

1. **Поиск компаний**
   - /start → "🔍 Поиск компаний"
   - Ввести город (например, "Алматы")
   - Выбрать категорию (например, "Салоны красоты")
   - Просмотреть найденные компании

2. **Сохранить лид**
   - Нажать "💾 Сохранить" на карточке компании
   - Лид добавится в CRM

3. **AI-анализ**
   - Нажать "🔬 Анализ" на карточке
   - Получить оценку потенциала (0-100) и рекомендации

4. **Генерация сообщения**
   - После анализа: "✉️ Сгенерировать сообщения"
   - Получить 2 варианта (короткое и развёрнутое)

5. **Работа с CRM**
   - /start → "📊 CRM"
   - Просмотр всех лидов
   - Изменение статусов
   - Добавление заметок
   - Напоминания

---

## 🔧 Опциональная настройка

### Redis для FSM persistence

**Docker (рекомендуется):**

Добавить в `docker-compose.yml`:
```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
```

Добавить в `.env`:
```env
REDIS_URL=redis://redis:6379/0
```

Запустить:
```bash
docker-compose up -d redis bot
```

**Локально:**

```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl start redis-server

# Mac
brew install redis
brew services start redis
```

Добавить в `.env`:
```env
REDIS_URL=redis://localhost:6379/0
```

### Access Control (ограничение доступа)

Добавить в `.env`:
```env
ALLOWED_USER_IDS=123456789,987654321
```

Узнать свой Telegram ID: @userinfobot

### LLM Daily Limit

Добавить в `.env`:
```env
LLM_DAILY_LIMIT=100  # 0 = без лимита
```

---

## 🐛 Troubleshooting

### Бот не стартует

```bash
# Проверить токен
python scripts/healthcheck.py

# Проверить LLM
python scripts/smoke_llm.py

# Проверить логи
docker-compose logs bot  # Docker
python bot.py            # Локально
```

### "Module not found"

```bash
# Переустановить зависимости
pip install -r requirements-lock.txt

# Docker - пересобрать
docker-compose build bot
```

### "Redis connection failed"

**Если не нужен:**
```env
# Убрать из .env
# REDIS_URL=
```

**Если нужен:**
```bash
# Проверить Redis
redis-cli ping  # Должно вернуть PONG

# Docker
docker ps | grep redis
```

---

## 📚 Дальше

- [README.md](README.md) - полная документация
- [DEPLOYMENT.md](DEPLOYMENT.md) - production деплой
- [FIXES_APPLIED.md](FIXES_APPLIED.md) - что исправлено в v2.0
- [VERIFICATION_CHECKLIST.md](VERIFICATION_CHECKLIST.md) - чеклист проверки

---

## 🎉 Готово!

Бот запущен и готов к использованию. Отправьте `/start` в Telegram.

**Вопросы?** Проверьте [README.md](README.md) или [Troubleshooting](#troubleshooting)
