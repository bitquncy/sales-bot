@echo off
rem chcp 65001 -> консоль читает UTF-8, чтобы русский текст ниже не превращался
rem в кракозябры под кодовой страницей cmd по умолчанию (866/1251).
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo [ERROR] venv не найден. Сначала выполни: py -3.11 -m venv venv
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python bot.py
pause
