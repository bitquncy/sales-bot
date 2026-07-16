FROM python:3.11-slim

WORKDIR /app

# Только production-зависимости (без pytest/ruff/mypy)
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

# Копируем только исходный код (тесты, документация, .git исключены через .dockerignore)
COPY . .

# Данные (БД, сессия Telethon, бэкапы) монтируются как том — не хранятся в образе
VOLUME ["/app/data"]

ENV DB_URL=sqlite+aiosqlite:////app/data/sales_agent.db
ENV CHAT_MONITOR_SESSION_PATH=/app/data/chat_monitor.session
ENV HEARTBEAT_FILE=/app/data/chat_monitor.heartbeat
ENV BACKUP_DIR=/app/data/backups

# Healthcheck: проверяем что процесс жив (бот не имеет HTTP-эндпоинта)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, sys; sys.exit(0 if os.path.exists('/app/bot.py') else 1)"

CMD ["python", "bot.py"]
