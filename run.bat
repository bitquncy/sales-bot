@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem AI Sales Agent Bot launcher for Windows.
rem This file is intentionally ASCII-only: cmd.exe may misparse UTF-8 batch
rem files before CHCP takes effect.

cd /d "%~dp0"
set "PY=venv\Scripts\python.exe"
set "PYTHONUTF8=1"

echo.
echo ============================================
echo   AI Sales Agent Bot - startup checks
echo ============================================
echo.

if not exist "%PY%" (
    echo [ERROR] Project virtual environment was not found: %PY%
    echo.
    echo Create it with:
    echo   py -3.11 -m venv venv
    echo   venv\Scripts\python.exe -m pip install --upgrade pip
    echo   venv\Scripts\python.exe -m pip install -r requirements-lock.txt
    echo.
    if /i not "%~1"=="--check" pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env was not found.
    echo Create it with: copy .env.example .env
    echo Then configure BOT_TOKEN, LLM credentials and ALLOWED_USER_IDS.
    if /i not "%~1"=="--check" pause
    exit /b 1
)

echo [INFO] Python runtime:
"%PY%" --version
if errorlevel 1 goto :runtime_error

echo [INFO] Checking runtime dependencies...
"%PY%" -c "import aiogram, sqlalchemy, aiosqlite, redis, sentry_sdk, cryptography, alembic"
if errorlevel 1 (
    echo [ERROR] Runtime dependencies are missing or outdated.
    echo Install them with:
    echo   "%PY%" -m pip install -r requirements-lock.txt
    if /i not "%~1"=="--check" pause
    exit /b 1
)

echo [INFO] Validating configuration...
"%PY%" -m scripts.check_config
if errorlevel 1 (
    echo [ERROR] Configuration validation failed. Fix .env and retry.
    if /i not "%~1"=="--check" pause
    exit /b 1
)

if /i "%~1"=="--check" (
    echo [OK] Startup checks passed. Bot was not started.
    exit /b 0
)

echo.
echo ============================================
echo   Starting bot
echo ============================================
echo [INFO] Press Ctrl+C to stop.
echo.

"%PY%" bot.py
set "BOT_EXIT=%errorlevel%"

echo.
if "%BOT_EXIT%"=="0" (
    echo [INFO] Bot stopped normally.
) else (
    echo [ERROR] Bot exited with code %BOT_EXIT%.
    echo Run this diagnostic command if needed:
    echo   "%PY%" scripts\healthcheck.py
)

pause
exit /b %BOT_EXIT%

:runtime_error
echo [ERROR] Failed to run Python from the project virtual environment.
if /i not "%~1"=="--check" pause
exit /b 1
