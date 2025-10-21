@echo off
setlocal

REM AutoTQ Device Info Display
REM Shows MAC addresses and firmware versions of connected devices

REM Check if venv exists
if not exist .\.venv\Scripts\python.exe (
  echo [ERROR] Python environment not found. Please run setup_all.bat first.
  echo.
  pause
  exit /b 1
)

REM Run the device info script
.\.venv\Scripts\python.exe autotq_device_info.py

exit /b %errorlevel%

