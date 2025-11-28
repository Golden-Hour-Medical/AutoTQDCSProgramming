@echo off
setlocal EnableDelayedExpansion
set PYTHONUTF8=1
set SSL_CERT_FILE=
set REQUESTS_CA_BUNDLE=

:: Find Python - prefer venv, fall back to system python
set PYTHON=
if exist ".\.venv\Scripts\python.exe" (
    set PYTHON=.\.venv\Scripts\python.exe
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set PYTHON=python
    ) else (
        where py >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set PYTHON=py
        )
    )
)

if "%PYTHON%"=="" (
    echo [ERROR] Python not found!
    echo.
    echo Please either:
    echo   1. Run setup_all.bat to create virtual environment
    echo   2. Install Python 3.8+ and add to PATH
    echo.
    pause
    exit /b 1
)

:MENU
cls
echo.
echo  ============================================================
echo  ^|                                                          ^|
echo  ^|              AutoTQ Production Tools Menu                 ^|
echo  ^|                                                          ^|
echo  ============================================================
echo.
echo  ---------------------- AUTHENTICATION ----------------------
echo.
echo    [1]  Check Authentication
echo         Check if your API key is valid and working
echo.
echo    [2]  Login ^& Generate API Key
echo         Login with username/password to create a new API key
echo.
echo    [3]  Check ^& Login (Auto)
echo         Check auth first, login only if needed
echo.
echo  ---------------------- FULL WORKFLOWS ----------------------
echo.
echo    [4]  Full Production Flow (Recommended)
echo         Complete workflow: firmware + audio + register device
echo         Includes PPK2 power, testing, and database registration
echo.
echo    [5]  Setup ^& Program (Simple)
echo         Download latest files and program single device
echo         Firmware + audio transfer
echo.
echo    [6]  Setup Only
echo         Download/update firmware and audio files from server
echo         Does NOT program any devices
echo.
echo  ---------------------- FIRMWARE ONLY -----------------------
echo.
echo    [7]  Flash Firmware Only
echo         Flash firmware to a single device (no audio)
echo.
echo    [8]  Program Device (Firmware + Audio)
echo         Flash firmware AND transfer audio to single device
echo.
echo  ---------------------- AUDIO ONLY --------------------------
echo.
echo    [9]  Bulk Audio Transfer (Multiple Devices)
echo         Transfer audio files to many devices in parallel
echo         Perfect for production lines
echo.
echo   [10]  Single Device Audio Transfer
echo         Transfer audio files to one device only
echo.
echo  ---------------------- DEVICE INFO -------------------------
echo.
echo   [11]  Show Device Info
echo         Display MAC address, firmware version of connected devices
echo.
echo   [12]  Check Serial Ports
echo         List all available COM ports and detect AutoTQ devices
echo.
echo   [13]  Quick Device Check
echo         Fast check of connected device status
echo.
echo  ---------------------- REPORTS -----------------------------
echo.
echo   [14]  Generate PCB Report
echo         Create CSV report of PCB test results
echo.
echo  ---------------------- OTHER -------------------------------
echo.
echo   [15]  Install USB Drivers
echo         Install required USB/serial drivers
echo.
echo    [0]  Exit
echo.
echo  ============================================================
echo.

set /p CHOICE="  Enter your choice [0-15]: "

if "%CHOICE%"=="0" goto EXIT
if "%CHOICE%"=="1" goto CHECK_AUTH
if "%CHOICE%"=="2" goto LOGIN
if "%CHOICE%"=="3" goto CHECK_AND_LOGIN
if "%CHOICE%"=="4" goto UNIFIED_PRODUCTION
if "%CHOICE%"=="5" goto SETUP_AND_PROGRAM
if "%CHOICE%"=="6" goto SETUP_ONLY
if "%CHOICE%"=="7" goto FIRMWARE_ONLY
if "%CHOICE%"=="8" goto PROGRAM_DEVICE
if "%CHOICE%"=="9" goto BULK_AUDIO
if "%CHOICE%"=="10" goto SINGLE_AUDIO
if "%CHOICE%"=="11" goto DEVICE_INFO
if "%CHOICE%"=="12" goto CHECK_PORTS
if "%CHOICE%"=="13" goto QUICK_CHECK
if "%CHOICE%"=="14" goto PCB_REPORT
if "%CHOICE%"=="15" goto INSTALL_DRIVERS

echo.
echo  [!] Invalid choice. Please try again.
timeout /t 2 >nul
goto MENU

:CHECK_AUTH
cls
echo.
echo  ============================================================
echo   Checking Authentication...
echo  ============================================================
echo.
%PYTHON% autotq_check_auth.py
goto PAUSE_AND_RETURN

:LOGIN
cls
echo.
echo  ============================================================
echo   Login ^& Generate API Key
echo  ============================================================
echo.
%PYTHON% autotq_login.py
goto PAUSE_AND_RETURN

:CHECK_AND_LOGIN
cls
echo.
echo  ============================================================
echo   Check ^& Login (Auto)
echo  ============================================================
echo.
call check_and_login.bat
goto PAUSE_AND_RETURN

:UNIFIED_PRODUCTION
cls
echo.
echo  ============================================================
echo   Full Production Flow
echo  ============================================================
echo.
echo  This will:
echo    - Check/download latest firmware and audio
echo    - Configure PPK2 power supply (4.2V)
echo    - Flash firmware to device
echo    - Transfer audio files
echo    - Register device in database
echo    - Run production tests
echo.
echo  Press Ctrl+C to cancel, or
pause
%PYTHON% autotq_unified_production.py
goto PAUSE_AND_RETURN

:SETUP_AND_PROGRAM
cls
echo.
echo  ============================================================
echo   Setup ^& Program
echo  ============================================================
echo.
echo  This will:
echo    - Download latest firmware and audio files
echo    - Flash firmware to connected device
echo    - Transfer audio files
echo.
pause
call setup_and_program.bat
goto PAUSE_AND_RETURN

:SETUP_ONLY
cls
echo.
echo  ============================================================
echo   Setup Only (Download Files)
echo  ============================================================
echo.
echo  Downloading latest firmware and audio files from server...
echo.
%PYTHON% autotq_setup.py
goto PAUSE_AND_RETURN

:FIRMWARE_ONLY
cls
echo.
echo  ============================================================
echo   Flash Firmware Only
echo  ============================================================
echo.
echo  This will flash firmware to the connected device.
echo  Audio files will NOT be transferred.
echo.
pause
%PYTHON% autotq_firmware_programmer.py
goto PAUSE_AND_RETURN

:PROGRAM_DEVICE
cls
echo.
echo  ============================================================
echo   Program Device (Firmware + Audio)
echo  ============================================================
echo.
echo  This will:
echo    - Flash firmware to device
echo    - Transfer all audio files
echo.
pause
%PYTHON% autotq_programmer.py
goto PAUSE_AND_RETURN

:BULK_AUDIO
cls
echo.
echo  ============================================================
echo   Bulk Audio Transfer (Multiple Devices)
echo  ============================================================
echo.
echo  This will transfer audio files to ALL connected AutoTQ devices
echo  simultaneously using parallel threads.
echo.
echo  Connect multiple devices before continuing.
echo.
pause
%PYTHON% autotq_bulk_audio_transfer.py
goto PAUSE_AND_RETURN

:SINGLE_AUDIO
cls
echo.
echo  ============================================================
echo   Single Device Audio Transfer
echo  ============================================================
echo.
echo  This will transfer audio files to ONE device.
echo.
pause
%PYTHON% autotq_programmer.py --audio-only
goto PAUSE_AND_RETURN

:DEVICE_INFO
cls
echo.
echo  ============================================================
echo   Device Information
echo  ============================================================
echo.
%PYTHON% autotq_device_info.py
goto PAUSE_AND_RETURN

:CHECK_PORTS
cls
echo.
echo  ============================================================
echo   Check Serial Ports
echo  ============================================================
echo.
%PYTHON% check_port.py
goto PAUSE_AND_RETURN

:QUICK_CHECK
cls
echo.
echo  ============================================================
echo   Quick Device Check
echo  ============================================================
echo.
%PYTHON% autotq_quick_check.py
goto PAUSE_AND_RETURN

:PCB_REPORT
cls
echo.
echo  ============================================================
echo   Generate PCB Report
echo  ============================================================
echo.
%PYTHON% pcb_stage_report.py
goto PAUSE_AND_RETURN

:INSTALL_DRIVERS
cls
echo.
echo  ============================================================
echo   Install USB Drivers
echo  ============================================================
echo.
call install_drivers.bat
goto PAUSE_AND_RETURN

:PAUSE_AND_RETURN
echo.
echo  ============================================================
echo   Press any key to return to menu...
echo  ============================================================
pause >nul
goto MENU

:EXIT
cls
echo.
echo  ============================================================
echo   Goodbye! 
echo  ============================================================
echo.
exit /b 0
