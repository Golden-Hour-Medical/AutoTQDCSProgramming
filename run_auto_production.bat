@echo off
setlocal enabledelayedexpansion

echo ---------------------------------------------------
echo ⚡ Starting AutoTQ Production Station
echo ---------------------------------------------------

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found! Please install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
)

REM Install Dependencies
echo 📦 Checking dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ Failed to install dependencies.
    pause
    exit /b 1
)

echo ✅ Dependencies verified.
echo.
echo 🚀 Launching Production Station...
echo.

python autotq_auto_production.py %*

if %errorlevel% neq 0 (
    echo.
    echo ⚠️ Script exited with error.
    pause
)
