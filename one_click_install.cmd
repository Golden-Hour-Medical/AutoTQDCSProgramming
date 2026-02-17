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
set "VERSION_FILE=%INSTALL_ROOT%\installed_source_version.txt"
set "REMOTE_VERSION_FILE=%TEMP%\autotq_remote_version.txt"
set "NEED_DOWNLOAD=1"

if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%" >nul 2>&1

del "%REMOTE_VERSION_FILE%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$h=(Invoke-WebRequest -UseBasicParsing -Method Head '%REPO_ZIP_URL%').Headers;" ^
  "$v=$h.ETag; if(-not $v){$v=$h.'Last-Modified'}; if(-not $v){$v='always-download'};" ^
  "Set-Content -Path '%REMOTE_VERSION_FILE%' -Value $v -NoNewline"
if not errorlevel 1 (
  for /f "usebackq delims=" %%V in ("%REMOTE_VERSION_FILE%") do set "REMOTE_VERSION=%%V"
)
if not defined REMOTE_VERSION set "REMOTE_VERSION=always-download"
del "%REMOTE_VERSION_FILE%" >nul 2>&1

if exist "%APP_DIR%\run_auto_production.bat" if exist "%VERSION_FILE%" (
  set /p LOCAL_VERSION=<"%VERSION_FILE%"
  if /i "%REMOTE_VERSION%" NEQ "always-download" if /i "%LOCAL_VERSION%"=="%REMOTE_VERSION%" set "NEED_DOWNLOAD=0"
)

if "%NEED_DOWNLOAD%"=="1" (
  echo [INFO] Update detected. Downloading latest AutoTQ package...
  set "AUTOTQ_REMOTE_VERSION=%REMOTE_VERSION%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$ProgressPreference='SilentlyContinue';" ^
    "if(Test-Path '%EXTRACT_DIR%'){Remove-Item -Recurse -Force '%EXTRACT_DIR%'};" ^
    "Invoke-WebRequest -UseBasicParsing '%REPO_ZIP_URL%' -OutFile '%ZIP_PATH%';" ^
    "Expand-Archive -Force '%ZIP_PATH%' '%EXTRACT_DIR%';" ^
    "$src=(Get-ChildItem '%EXTRACT_DIR%' -Directory | Select-Object -First 1).FullName;" ^
    "if(-not $src){throw 'Extracted folder not found'};" ^
    "if(-not (Test-Path '%APP_DIR%')){New-Item -ItemType Directory -Force -Path '%APP_DIR%' | Out-Null};" ^
    "Copy-Item -Path (Join-Path $src '*') -Destination '%APP_DIR%' -Recurse -Force;" ^
    "Remove-Item -Force '%ZIP_PATH%' -ErrorAction SilentlyContinue;" ^
    "Remove-Item -Recurse -Force '%EXTRACT_DIR%' -ErrorAction SilentlyContinue;" ^
    "Set-Content -Path '%VERSION_FILE%' -Value $env:AUTOTQ_REMOTE_VERSION -NoNewline"
  if errorlevel 1 (
    echo.
    echo [ERROR] Download or extraction failed.
    pause
    exit /b 1
  )
) else (
  echo [INFO] AutoTQ is already up to date. Skipping download.
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
