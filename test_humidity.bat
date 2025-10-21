@echo off
setlocal

REM ESPEC Chamber Humidity Command Tester

REM Check if venv exists
if not exist .\.venv\Scripts\python.exe (
  echo [ERROR] Python environment not found. Please run setup_all.bat first.
  echo.
  pause
  exit /b 1
)

REM Ensure pyvisa is available
.\.venv\Scripts\python -c "import pyvisa" >nul 2>&1 || (
  echo Installing pyvisa...
  .\.venv\Scripts\pip install --no-input pyvisa || (
    echo [ERROR] Failed to install pyvisa.
    pause
    exit /b 1
  )
)

REM Run the test
.\.venv\Scripts\python.exe test_humidity_commands.py

exit /b %errorlevel%

