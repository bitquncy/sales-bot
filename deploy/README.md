# Деплой Sales Agent Bot (Linux / systemd)

## Быстрый старт

1. Скопируй unit-файлы в systemd:
```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
```

2. Отредактируй пути и пользователя в каждом `.service` файле:
   - Замени `YOUR_USER` на своего пользователя (например, `ubuntu`)
   - Замени `/path/to/sales_agent_bot` на реальный путь к проекту

3. Перезагрузи systemd и включи сервисы:
```bash
sudo systemctl daemon-reload

# Основной бот
sudo systemctl enable --now sales-bot.service

# Chat Monitor (только если настроен Telethon в .env)
sudo systemctl enable --now sales-chat-monitor.service

# Автобэкап БД (раз в сутки в 03:00)
sudo systemctl enable --now sales-backup.timer

# Проверка heartbeat Chat Monitor (раз в час)
sudo systemctl enable --now sales-heartbeat.timer
```

## Управление

```bash
# Статус
sudo systemctl status sales-bot.service
sudo systemctl status sales-chat-monitor.service

# Логи
sudo journalctl -u sales-bot.service -f
sudo journalctl -u sales-chat-monitor.service -f

# Перезапуск
sudo systemctl restart sales-bot.service

# Ручной бэкап
sudo systemctl start sales-backup.service

# Ручная проверка heartbeat
sudo systemctl start sales-heartbeat.service
```

## Windows (Task Scheduler)

Для Windows используй `run.bat` или настрой задачи через Task Scheduler:

- **Бот:** `venv\Scripts\python.exe bot.py` — при входе в систему, перезапуск при сбое
- **Chat Monitor:** `venv\Scripts\python.exe -m chat_monitor.runner`
- **Бэкап:** `venv\Scripts\python.exe -m scripts.backup_db` — ежедневно в 03:00
- **Heartbeat:** `venv\Scripts\python.exe -m scripts.check_heartbeat` — каждый час
