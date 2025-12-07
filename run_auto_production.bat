@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ===================================================
echo ⚡ Starting AutoTQ Production Station
echo ===================================================

REM ----------------------------------------------------
REM 1. DETECT PYTHON (Robust Method)
REM ----------------------------------------------------
set "PYEXE="

REM A) Check for Virtual Environment first (best practice)
if exist ".venv\Scripts\python.exe" (
    set "PYEXE=.venv\Scripts\python.exe"
    echo [INFO] Using virtual environment: !PYEXE!
    goto :FOUND
)

REM B) Check for 'py' launcher (standard Windows Python launcher)
where py >nul 2>&1
if %errorlevel% equ 0 (
    REM Check if py can run -3
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYEXE=py -3"
        echo [INFO] Using Python Launcher 'py'
        goto :FOUND
    )
)

REM C) Check standard installation paths (3.12 down to 3.8)
for %%v in (312 311 310 39 38) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" (
        set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
        echo [INFO] Found Python %%v in AppData
        goto :FOUND
    )
    if exist "%ProgramFiles%\Python%%v\python.exe" (
        set "PYEXE=%ProgramFiles%\Python%%v\python.exe"
        echo [INFO] Found Python %%v in Program Files
        goto :FOUND
    )
    if exist "C:\Python%%v\python.exe" (
        set "PYEXE=C:\Python%%v\python.exe"
        echo [INFO] Found Python %%v in C:\
        goto :FOUND
    )
)

REM D) Check PATH (but filter out Windows Store shim)
for /f "usebackq delims=" %%P in (`where python 2^>nul`) do (
    echo %%P | find /i "WindowsApps" >nul && (
        REM Skip Windows Store shim which causes "Python not found" GUI popup
    ) || (
        if not defined PYEXE (
            set "PYEXE=%%P"
            echo [INFO] Found Python in PATH: %%P
            goto :FOUND
        )
    )
)

REM ----------------------------------------------------
REM 2. PYTHON NOT FOUND - ATTEMPT INSTALL OR EXIT
REM ----------------------------------------------------
if not defined PYEXE (
    echo.
    echo ❌ Python not found!
    echo.
    echo We can attempt to install Python 3.11 automatically via Winget.
    echo Or you can install it manually from python.org.
    echo.
    choice /M "Attempt automatic installation?"
    if !errorlevel! equ 1 (
        echo.
        echo 📦 Installing Python 3.11...
        winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
        if !errorlevel! equ 0 (
            echo ✅ Installation successful! Restarting script...
            echo.
            REM Try to find it again immediately
            if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
            if not defined PYEXE set "PYEXE=python"
            goto :FOUND
        ) else (
            echo ❌ Installation failed. Please install Python manually.
            pause
            exit /b 1
        )
    ) else (
        echo Please install Python 3.8+ and try again.
        pause
        exit /b 1
    )
)

:FOUND
REM ----------------------------------------------------
REM 3. INSTALL DEPENDENCIES
REM ----------------------------------------------------
echo.
echo 📦 Checking dependencies...
"%PYEXE%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ❌ Failed to install dependencies!
    echo Check your internet connection or try running as Administrator.
    pause
    exit /b 1
)

echo ✅ Dependencies verified.

REM ----------------------------------------------------
REM 4. RUN SCRIPT
REM ----------------------------------------------------
echo.
echo 🚀 Launching Production Station...
echo.

"%PYEXE%" autotq_auto_production.py %*

if %errorlevel% neq 0 (
    echo.
    echo ⚠️ Script exited with error code %errorlevel%.
    pause
)
