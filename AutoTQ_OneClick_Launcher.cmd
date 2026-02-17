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

curl -fsSL "%INSTALLER_URL%" -o "%INSTALLER_PATH%"
if errorlevel 1 (
  echo [ERROR] Could not download installer.
  echo Check internet connection and try again.
  pause
  exit /b 1
)

call "%INSTALLER_PATH%"
exit /b %errorlevel%
