#!/usr/bin/env bash
# Fail-closed production deployment for Docker Compose.
set -euo pipefail

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.production.yml)

if [[ ! -f .env ]]; then
    echo "[ERROR] .env is missing. Copy .env.example and fill rotated production secrets."
    exit 1
fi

echo "[1/6] Validating production Compose configuration..."
"${COMPOSE[@]}" --profile postgres config --quiet

echo "[2/6] Starting PostgreSQL and Redis..."
"${COMPOSE[@]}" --profile postgres up -d postgres redis

echo "[3/6] Applying Alembic migrations..."
"${COMPOSE[@]}" --profile postgres run --rm migrate

echo "[4/6] Running production readiness checks..."
"${COMPOSE[@]}" --profile postgres run --rm bot python -m scripts.production_readiness

echo "[5/6] Starting bot..."
"${COMPOSE[@]}" --profile postgres up -d bot

echo "[6/6] Showing service status..."
"${COMPOSE[@]}" --profile postgres ps
echo "[OK] Production deployment flow completed."
