$ErrorActionPreference = "Stop"

$compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.production.yml")

if (-not (Test-Path -LiteralPath ".env")) {
    throw ".env is missing. Copy .env.example and fill rotated production secrets."
}

Write-Host "[1/6] Validating production Compose configuration..."
docker @compose --profile postgres config --quiet

Write-Host "[2/6] Starting PostgreSQL and Redis..."
docker @compose --profile postgres up -d postgres redis

Write-Host "[3/6] Applying Alembic migrations..."
docker @compose --profile postgres run --rm migrate

Write-Host "[4/6] Running production readiness checks..."
docker @compose --profile postgres run --rm bot python -m scripts.production_readiness

Write-Host "[5/6] Starting bot..."
docker @compose --profile postgres up -d bot

Write-Host "[6/6] Showing service status..."
docker @compose --profile postgres ps
Write-Host "[OK] Production deployment flow completed."
