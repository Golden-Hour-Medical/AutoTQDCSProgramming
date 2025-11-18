@echo off
REM Quick Port Checker - Diagnose COM port issues
REM Usage: check_port.bat COM229

if "%1"=="" (
  echo Usage: check_port.bat COMxx
  echo Example: check_port.bat COM229
  echo.
  echo Or run without arguments to auto-detect:
  .\.venv\Scripts\python.exe check_port.py
) else (
  .\.venv\Scripts\python.exe check_port.py %1
)

pause

