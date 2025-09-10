@echo off
REM AutoTQ Programming Tools - Windows Setup and Program Script
REM This script downloads the latest files and then programs devices

echo ==========================================
echo   AutoTQ Programming Tools for Windows
echo ==========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.8+ and add it to your PATH
    echo Download from: https://python.org/downloads/
    pause
    exit /b 1
)

echo Step 1: Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt ppk2_api
if errorlevel 1 (
    echo ERROR: Failed to install packages
    echo Try running as Administrator
    pause
    exit /b 1
)

echo.
echo Step 2: Downloading latest firmware and audio files...
python autotq_setup.py
if errorlevel 1 (
    echo ERROR: Setup failed
    echo Check your internet connection and credentials
    pause
    exit /b 1
)

echo.
echo Step 3: Programming device(s) with optimized settings...
python autotq_programmer.py
if errorlevel 1 (
    echo ERROR: Programming failed
    echo Check device connection and try again
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   SUCCESS! Device programming completed
echo   Production mode optimizations used
echo ==========================================
echo.
pause 