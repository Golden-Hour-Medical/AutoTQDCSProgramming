@echo off
setlocal
set PYTHONUTF8=1
set SSL_CERT_FILE=
set REQUESTS_CA_BUNDLE=

echo ========================================
echo AutoTQ Bulk Audio Transfer Tool
echo ========================================
echo.
echo This tool will detect all connected AutoTQ devices
echo and transfer audio files to all of them simultaneously.
echo.
echo Usage examples:
echo   run_bulk_audio.bat                  - Normal mode with prompts
echo   run_bulk_audio.bat --no-prompt      - Start immediately without confirmation
echo   run_bulk_audio.bat --speed ultrafast - Use fastest transfer speed
echo   run_bulk_audio.bat --continuous     - Keep running and detect new devices
echo.

REM Check if virtual environment exists
if not exist ".\.venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please run setup_all.bat first.
    pause
    exit /b 1
)

REM Run the bulk audio transfer script
.\.venv\Scripts\python.exe autotq_bulk_audio_transfer.py %*

REM Pause if not in continuous mode or if error occurred
if errorlevel 1 (
    echo.
    pause
)

