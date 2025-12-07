@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ===================================================
echo Starting AutoTQ Production Station
echo ===================================================

REM ----------------------------------------------------
REM 1. DETECT PYTHON
REM ----------------------------------------------------
set "PYEXE="
set "VENV_PYTHON=.venv\Scripts\python.exe"

REM A) Check for Virtual Environment first
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -m pip --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYEXE=%VENV_PYTHON%"
        echo [INFO] Using virtual environment
        goto :FOUND
    ) else (
        echo [WARN] Virtual environment corrupted. Recreating...
        rmdir /s /q .venv 2>nul
    )
)

REM B) Find system Python
set "SYS_PYTHON="

where py >nul 2>&1
if !errorlevel! equ 0 (
    set "SYS_PYTHON=py"
    echo [INFO] Found py launcher
    goto :HAVE_SYSTEM_PYTHON
)

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "C:\Python311\python.exe" (
    set "SYS_PYTHON=C:\Python311\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)

where python >nul 2>&1
if !errorlevel! equ 0 (
    set "SYS_PYTHON=python"
    echo [INFO] Found python in PATH
    goto :HAVE_SYSTEM_PYTHON
)

echo.
echo ERROR: Python not found!
echo Please install Python 3.8+ from python.org
pause
exit /b 1

:HAVE_SYSTEM_PYTHON
echo [INFO] Using: %SYS_PYTHON%

REM ----------------------------------------------------
REM 2. CREATE VENV IF NEEDED
REM ----------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Creating virtual environment...
    %SYS_PYTHON% -m venv .venv
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment created.
)

set "PYEXE=.venv\Scripts\python.exe"

REM Ensure pip works
"%PYEXE%" -m ensurepip --upgrade >nul 2>&1
"%PYEXE%" -m pip install --upgrade pip >nul 2>&1

:FOUND
REM ----------------------------------------------------
REM 3. INSTALL DEPENDENCIES
REM ----------------------------------------------------
echo.
echo Checking dependencies...
"%PYEXE%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)

echo Dependencies OK.

REM ----------------------------------------------------
REM 4. RUN SCRIPT
REM ----------------------------------------------------
echo.
echo Launching Production Station...
echo.

"%PYEXE%" autotq_auto_production.py %*

if %errorlevel% neq 0 (
    echo.
    echo Script exited with error.
    pause
)
