@echo off
setlocal
title AutoTQ One-Click Launcher

echo ===================================================
echo AutoTQ One-Click Launcher
echo ===================================================
echo.
echo Downloading installer and starting setup...
echo.

set "INSTALLER_URL=https://raw.githubusercontent.com/Golden-Hour-Medical/AutoTQDCSProgramming/main/one_click_install.cmd"
set "INSTALLER_PATH=%TEMP%\one_click_install.cmd"
set "SHA_FILE=%TEMP%\autotq_latest_sha.txt"
set "OWNER_REPO=Golden-Hour-Medical/AutoTQDCSProgramming"
set "RAW_URL="
set "CACHE_BUST=%RANDOM%%RANDOM%"

del /f /q "%INSTALLER_PATH%" >nul 2>&1
del /f /q "%SHA_FILE%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$api='https://api.github.com/repos/%OWNER_REPO%/commits/main';" ^
  "$resp=Invoke-RestMethod -UseBasicParsing -Uri $api;" ^
  "$sha=$resp.sha; if(-not $sha){throw 'sha missing'};" ^
  "Set-Content -LiteralPath '%SHA_FILE%' -Value $sha -NoNewline"

if not errorlevel 1 (
  for /f "usebackq delims=" %%S in ("%SHA_FILE%") do set "RAW_URL=https://raw.githubusercontent.com/%OWNER_REPO%/%%S/one_click_install.cmd"
) else (
  set "RAW_URL=%INSTALLER_URL%"
)

curl -fsSL "%RAW_URL%?nocache=%CACHE_BUST%" -o "%INSTALLER_PATH%"
if errorlevel 1 (
  echo [WARN] SHA-pinned download failed, trying main branch fallback...
  curl -fsSL "%INSTALLER_URL%?nocache=%CACHE_BUST%" -o "%INSTALLER_PATH%"
)

if errorlevel 1 (
  echo [ERROR] Could not download installer.
  echo Check internet connection and try again.
  pause
  exit /b 1
)

call "%INSTALLER_PATH%"
exit /b %errorlevel%
