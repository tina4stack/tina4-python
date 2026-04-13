@echo off
REM Tina4 Store Demo — One-command setup (Windows)
REM Usage: setup.bat

echo === Tina4 Store (Python) Setup ===
echo.

REM Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.12+ from https://python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    exit /b 1
)

python --version
echo [OK] Python found

REM Create venv if missing
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)

REM Install from local framework source
echo Installing tina4-python from local source...
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r requirements.txt
echo [OK] tina4-python installed

REM Create .env if missing
if not exist .env (
    copy .env.example .env >nul
    echo [OK] Created .env from .env.example
) else (
    echo [OK] .env exists
)

REM Create data directories
if not exist data\sessions mkdir data\sessions
if not exist data\queue mkdir data\queue
if not exist data\mailbox mkdir data\mailbox
if not exist src\public\uploads mkdir src\public\uploads
echo [OK] Data directories ready

echo.
echo === Setup complete! ===
echo.
echo Start the server:
echo   .venv\Scripts\python app.py
echo.
echo Then open: http://localhost:7146
echo.
echo Admin login: admin@tina4store.com / admin123
