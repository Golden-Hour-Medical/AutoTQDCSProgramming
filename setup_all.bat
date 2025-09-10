@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ==========================================
echo   AutoTQ - One-Click Setup (Windows)
echo ==========================================

REM 1) Ensure Python 3.11 is available (avoid Windows Store shim)
set "PYEXE="

REM Prefer explicit known installs
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYEXE if exist "%ProgramFiles%\Python311\python.exe" set "PYEXE=%ProgramFiles%\Python311\python.exe"
if not defined PYEXE if exist "C:\Python311\python.exe" set "PYEXE=C:\Python311\python.exe"

REM Try py launcher for 3.11 specifically
if not defined PYEXE (
  where py >nul 2>&1 && ( py -3.11 -c "exit()" >nul 2>&1 && set "PYEXE=py -3.11" )
)

REM Fall back to PATH python if it's not the WindowsApps stub
if not defined PYEXE (
  for /f "usebackq delims=" %%P in (`where python 2^>nul`) do (
    echo %%P | find /i "WindowsApps" >nul && (
      REM skip Windows Store shim
      rem noop
    ) || (
      if not defined PYEXE set "PYEXE=%%P"
    )
  )
)

REM Install Python via winget if still not found
if not defined PYEXE (
  echo Python not found. Installing Python 3.11 ^(user scope^) via winget...
  winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements || (
    echo [ERROR] winget installation failed. Please install Python 3.11 manually.
    pause
    exit /b 1
  )
  REM Try common install locations after install
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  if not defined PYEXE if exist "%ProgramFiles%\Python311\python.exe" set "PYEXE=%ProgramFiles%\Python311\python.exe"
  if not defined PYEXE set "PYEXE=python"
)

echo Using Python: %PYEXE%

REM 2) Create venv and install dependencies
"%PYEXE%" -m venv .venv || (
  echo [ERROR] Failed to create venv.
  echo If this is the Microsoft Store shim, please rerun this script.
  pause
  exit /b 1
)
call .\.venv\Scripts\python -m pip install --upgrade pip || (
  echo [ERROR] Failed to upgrade pip.
  pause
  exit /b 1
)
call .\.venv\Scripts\pip install --no-input -r requirements.txt ppk2_api || (
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
