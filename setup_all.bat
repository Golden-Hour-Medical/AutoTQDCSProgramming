@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ==========================================
echo   AutoTQ - One-Click Setup (Windows)
echo ==========================================

REM 1) Ensure Python 3.11 is available
set PYEXE=
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  where py >nul 2>&1 && set "PYEXE=py -3.11"
)
if not defined PYEXE (
  echo Python not found. Installing Python 3.11 ^(user scope^) via winget...
  winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements || (
    echo [ERROR] winget installation failed. Please install Python 3.11 manually.
    pause
    exit /b 1
  )
  REM Try common install locations
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  if not defined PYEXE if exist "%ProgramFiles%\Python311\python.exe" set "PYEXE=%ProgramFiles%\Python311\python.exe"
  if not defined PYEXE set "PYEXE=python"
)

echo Using Python: %PYEXE%

REM 2) Create venv and install dependencies
%PYEXE% -m venv .venv || (
  echo [ERROR] Failed to create venv.
  pause
  exit /b 1
)
.\.venv\Scripts\python -m pip install --upgrade pip || (
  echo [ERROR] Failed to upgrade pip.
  pause
  exit /b 1
)
.\.venv\Scripts\pip install --no-input -r requirements.txt ppk2_api || (
  echo [ERROR] Failed to install dependencies.
  pause
  exit /b 1
)

echo.
echo [OK] Python and dependencies are ready.

echo.
echo Do you want to install USB drivers now? (recommended on clean PCs)
choice /M "Install drivers"
if %errorlevel%==1 (
  if exist install_drivers.bat (
    call install_drivers.bat
  ) else (
    echo install_drivers.bat not found; skipping.
  )
) else (
  echo Skipping driver installation.
)

echo.
echo ==========================================
echo   Setup complete. To start, run: run_unified.bat
echo ==========================================
exit /b 0
