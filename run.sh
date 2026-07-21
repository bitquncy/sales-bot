#!/usr/bin/env bash
# ============================================================================
# AI Sales Agent Bot - Launcher (Linux/macOS)
# ============================================================================
# Автоматический запуск бота с проверками окружения
# Поддерживает: bot + chat_monitor (если настроен)
# ============================================================================

set -e  # Остановка при ошибках

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Перейти в директорию скрипта
cd "$(dirname "$0")"

echo ""
echo "============================================"
echo "  AI Sales Agent Bot - Starting"
echo "============================================"
echo ""

# ===== Проверка 1: venv существует =====
if [ ! -f venv/bin/activate ]; then
    echo -e "${RED}[ERROR]${NC} venv не найден"
    echo ""
    echo "Создайте виртуальное окружение:"
    echo "  python3.11 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements-lock.txt"
    echo ""
    exit 1
fi

# ===== Проверка 2: .env файл существует =====
if [ ! -f .env ]; then
    echo -e "${YELLOW}[WARNING]${NC} .env не найден"
    echo ""
    echo "Создайте .env из примера:"
    echo "  cp .env.example .env"
    echo ""
    echo "Затем отредактируйте .env и укажите:"
    echo "  - BOT_TOKEN"
    echo "  - LLM_API_KEY"
    echo ""
    read -p "Продолжить без .env? (y/N): " continue
    if [[ ! "$continue" =~ ^[Yy]$ ]]; then
        exit 1
    fi
    echo ""
fi

# ===== Активация venv =====
echo -e "${BLUE}[INFO]${NC} Активирую venv..."
source venv/bin/activate

# ===== Проверка 3: Python версия =====
echo -e "${BLUE}[INFO]${NC} Проверяю версию Python..."
python_version=$(python --version 2>&1)
if ! echo "$python_version" | grep -qE "3\.(11|12)"; then
    echo -e "${YELLOW}[WARNING]${NC} Python не 3.11+ (рекомендуется 3.11)"
    echo "$python_version"
    echo ""
fi

# ===== Проверка 4: Зависимости установлены =====
echo -e "${BLUE}[INFO]${NC} Проверяю зависимости..."
if ! python -c "import aiogram, sqlalchemy, aiosqlite, redis, sentry_sdk, cryptography, alembic" 2>/dev/null; then
    echo -e "${RED}[ERROR]${NC} Зависимости не установлены"
    echo ""
    echo "Установите зависимости:"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements-lock.txt"
    echo ""
    exit 1
fi

# ===== Проверка 5: конфигурация теми же правилами, что bot.py =====
echo -e "${BLUE}[INFO]${NC} Проверяю конфигурацию..."
if ! python -m scripts.check_config; then
    echo -e "${RED}[ERROR]${NC} Конфигурация некорректна. Исправьте .env."
    exit 1
fi

# ===== Проверка 6: БД файл (опционально) =====
if [ -f sales_agent.db ]; then
    echo -e "${BLUE}[INFO]${NC} БД найдена: sales_agent.db"
else
    echo -e "${BLUE}[INFO]${NC} БД будет создана автоматически при первом запуске"
fi

# ===== Проверка 7: Redis (опционально) =====
config_redis_url=$(python -c "from config import settings; print(settings.redis_url)")
if [ -n "$config_redis_url" ]; then
    echo -e "${BLUE}[INFO]${NC} REDIS_URL настроен, проверяю доступность..."
    if python -m scripts.check_redis "$config_redis_url" 2>/dev/null; then
        echo -e "${GREEN}[INFO]${NC} Redis доступен ✓"
    else
        echo -e "${YELLOW}[WARNING]${NC} Redis недоступен, будет использован MemoryStorage"
    fi
fi

echo ""
echo "============================================"
echo "  Запуск бота..."
echo "============================================"
echo ""
echo -e "${BLUE}[INFO]${NC} Для остановки нажмите Ctrl+C"
echo -e "${BLUE}[INFO]${NC} Логи отображаются ниже:"
echo ""
echo "--------------------------------------------"
echo ""

# ===== Запуск бота =====
# Бот автоматически запустит chat_monitor как фоновую задачу (если настроен)
python bot.py
exitcode=$?

# ===== Обработка выхода =====
echo ""
echo "--------------------------------------------"
echo ""

if [ $exitcode -eq 0 ]; then
    echo -e "${GREEN}[INFO]${NC} Бот остановлен штатно"
else
    echo -e "${RED}[ERROR]${NC} Бот завершился с ошибкой (код: $exitcode)"
    echo ""
    echo "Проверьте логи выше или запустите:"
    echo "  python scripts/healthcheck.py"
    echo ""
fi

exit $exitcode
