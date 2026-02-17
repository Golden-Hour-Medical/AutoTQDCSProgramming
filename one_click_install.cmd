@echo off
setlocal
title AutoTQ One-Click Installer

echo ===================================================
echo AutoTQ One-Click Installer
echo ===================================================
echo.
echo This will download the latest AutoTQ tools and launch them.
echo.

set "REPO_ZIP_URL=https://github.com/Golden-Hour-Medical/AutoTQDCSProgramming/archive/refs/heads/main.zip"
set "INSTALL_ROOT=%LOCALAPPDATA%\AutoTQProduction"
set "ZIP_PATH=%TEMP%\AutoTQProduction.zip"
set "EXTRACT_DIR=%TEMP%\AutoTQProduction_extract"
set "APP_DIR=%INSTALL_ROOT%\app"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$ProgressPreference='SilentlyContinue';" ^
  "if(Test-Path '%EXTRACT_DIR%'){Remove-Item -Recurse -Force '%EXTRACT_DIR%'};" ^
  "Invoke-WebRequest -UseBasicParsing '%REPO_ZIP_URL%' -OutFile '%ZIP_PATH%';" ^
  "Expand-Archive -Force '%ZIP_PATH%' '%EXTRACT_DIR%';" ^
  "$src=(Get-ChildItem '%EXTRACT_DIR%' -Directory | Select-Object -First 1).FullName;" ^
  "if(-not $src){throw 'Extracted folder not found'};" ^
  "if(Test-Path '%APP_DIR%'){Remove-Item -Recurse -Force '%APP_DIR%'};" ^
  "New-Item -ItemType Directory -Force -Path '%APP_DIR%' | Out-Null;" ^
  "Copy-Item -Path (Join-Path $src '*') -Destination '%APP_DIR%' -Recurse -Force;" ^
  "Remove-Item -Force '%ZIP_PATH%' -ErrorAction SilentlyContinue;" ^
  "Remove-Item -Recurse -Force '%EXTRACT_DIR%' -ErrorAction SilentlyContinue;"

if errorlevel 1 (
  echo.
  echo [ERROR] Download or extraction failed.
  pause
  exit /b 1
)

if not exist "%APP_DIR%\run_auto_production.bat" (
  echo.
  echo [ERROR] run_auto_production.bat was not found after install.
  pause
  exit /b 1
)

echo.
echo [INFO] Launching AutoTQ...
call "%APP_DIR%\run_auto_production.bat"
exit /b %errorlevel%
