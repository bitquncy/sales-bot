#!/usr/bin/env bash
# deploy/install.sh — автоматическая установка systemd unit-файлов (DEVOPS-5).
# Подставляет реальные пути и пользователя, копирует в /etc/systemd/system/.
#
# Использование:
#   bash deploy/install.sh
#   bash deploy/install.sh --user myuser --dir /opt/sales_agent_bot
#   bash deploy/install.sh --dry-run   # показать что будет сделано без выполнения

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CURRENT_USER="${SUDO_USER:-$(whoami)}"
DRY_RUN=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)    CURRENT_USER="$2"; shift 2 ;;
        --dir)     PROJECT_DIR="$2";  shift 2 ;;
        --dry-run) DRY_RUN=true;      shift   ;;
        *) echo "Unknown option: $1"; exit 1  ;;
    esac
done

VENV_PYTHON="$PROJECT_DIR/venv/bin/python"

echo "═══════════════════════════════════════════════════════════"
echo "  Sales Agent Bot — установка systemd unit-файлов"
echo "═══════════════════════════════════════════════════════════"
echo "  Пользователь : $CURRENT_USER"
echo "  Директория   : $PROJECT_DIR"
echo "  Python       : $VENV_PYTHON"
echo "  Dry run      : $DRY_RUN"
echo ""

# ── Проверки ──────────────────────────────────────────────────────────────────
if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "❌ Директория проекта не найдена: $PROJECT_DIR"
    exit 1
fi

if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "⚠  venv не найден: $VENV_PYTHON"
    echo "   Создай его: python3.11 -m venv $PROJECT_DIR/venv"
    echo "   Установи зависимости: $PROJECT_DIR/venv/bin/pip install -r $PROJECT_DIR/requirements-lock.txt"
    if [[ "$DRY_RUN" == "false" ]]; then
        exit 1
    fi
fi

# ── Функция установки unit-файла ──────────────────────────────────────────────
install_unit() {
    local src="$SCRIPT_DIR/$1"
    local dst="/etc/systemd/system/$1"

    if [[ ! -f "$src" ]]; then
        echo "⚠  Файл не найден: $src (пропускаем)"
        return
    fi

    # Подставляем плейсхолдеры
    local content
    content=$(sed \
        -e "s|YOUR_USER|$CURRENT_USER|g" \
        -e "s|/path/to/sales_agent_bot|$PROJECT_DIR|g" \
        "$src")

    echo "  📄 $src → $dst"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "     [dry-run] содержимое:"
        echo "$content" | sed 's/^/     /'
    else
        echo "$content" | sudo tee "$dst" > /dev/null
        echo "     ✅ установлен"
    fi
}

# ── Установка unit-файлов ─────────────────────────────────────────────────────
echo "Устанавливаем unit-файлы..."
install_unit "sales-bot.service"
install_unit "sales-backup.service"
install_unit "sales-backup.timer"
install_unit "sales-heartbeat.service"
install_unit "sales-heartbeat.timer"

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "✅ Dry run завершён. Запусти без --dry-run для реальной установки."
    exit 0
fi

# ── Активация ─────────────────────────────────────────────────────────────────
echo ""
echo "Перезагружаем systemd..."
sudo systemctl daemon-reload

echo ""
echo "Включаем и запускаем сервисы..."
sudo systemctl enable --now sales-bot.service
echo "  ✅ sales-bot.service"

sudo systemctl enable --now sales-backup.timer
echo "  ✅ sales-backup.timer (ежедневный бэкап в 03:00)"

sudo systemctl enable --now sales-heartbeat.timer
echo "  ✅ sales-heartbeat.timer (проверка heartbeat каждый час)"

echo ""
echo "Chat Monitor запускается внутри sales-bot.service при полном CHAT_MONITOR_* конфиге."

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Установка завершена!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Полезные команды:"
echo "  sudo systemctl status sales-bot.service"
echo "  sudo journalctl -u sales-bot.service -f"
echo "  sudo systemctl restart sales-bot.service"
