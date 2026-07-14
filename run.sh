#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -f venv/bin/activate ]; then
    echo "[ERROR] venv не найден. Сначала выполни: python3.11 -m venv venv"
    exit 1
fi
source venv/bin/activate
python bot.py
