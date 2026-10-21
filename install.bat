@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.12 from https://www.python.org/downloads/ and check "Add python.exe to PATH".
    pause
    exit /b 1
)
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo.
echo Done. Next steps:
echo   1. Copy .env.example to .env and fill DISCORD_TOKEN / CALLS_CHANNEL_ID / GUILD_ID
echo   2. Run run.bat
pause
