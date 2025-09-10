@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ==========================================
echo   AutoTQ - Optional Driver Installer
echo ==========================================
echo.
echo This will attempt to install common USB serial drivers if their installers
echo are present in the ^"drivers^" folder. Internet may be required on first use.
echo.

REM --- Admin check ---
net session >nul 2>&1
if %errorlevel% NEQ 0 (
  echo [Warning] Not running as Administrator. Some drivers may fail to install.
  echo          Right-click and ^"Run as administrator^" for best results.
)

set DRV_DIR=%~dp0drivers
if not exist "%DRV_DIR%" (
  echo drivers folder not found. Create a ^"drivers^" folder and place installers inside.
  goto :end
)

REM --- Silicon Labs CP210x ---
set SILABS_EXE=
for %%F in (CP210xVCPInstaller_x64.exe CP210xVCPInstaller_x86.exe CP210xVCPInstaller.exe) do (
  if exist "%DRV_DIR%\%%F" set SILABS_EXE="%DRV_DIR%\%%F"
)
if defined SILABS_EXE (
  echo Installing Silicon Labs CP210x driver...
  %SILABS_EXE% /quiet || echo (CP210x installer returned a non-zero exit code)
) else (
  echo [Info] CP210x installer not found. Skipping.
)

REM --- FTDI VCP ---
set FTDI_EXE=
for %%F in (CDM*.exe FTDI*.exe) do (
  if exist "%DRV_DIR%\%%F" set FTDI_EXE="%DRV_DIR%\%%F"
)
if defined FTDI_EXE (
  echo Installing FTDI VCP driver...
  %FTDI_EXE% /S || echo (FTDI installer returned a non-zero exit code)
) else (
  echo [Info] FTDI installer not found. Skipping.
)

REM --- CH340/CH341 ---
set CH340_EXE=
for %%F in (CH341SER.EXE CH341SER64.EXE CH341SER*.EXE) do (
  if exist "%DRV_DIR%\%%F" set CH340_EXE="%DRV_DIR%\%%F"
)
if defined CH340_EXE (
  echo Installing CH340/CH341 driver...
  %CH340_EXE% /INSTALL || echo (CH340 installer may require manual confirmation)
) else (
  echo [Info] CH340/CH341 installer not found. Skipping.
)

REM --- Nordic PPK2 ---
echo [Info] PPK2 usually enumerates as a USB CDC device on Windows 10/11.
echo        If it does not appear as a COM port, install the CDC ACM driver.

REM Try to install Nordic CDC ACM driver from INF if provided
set NORDIC_DIR=%DRV_DIR%\nordic
if exist "%NORDIC_DIR%" (
  for %%I in ("%NORDIC_DIR%\*.inf") do (
    echo Installing Nordic CDC ACM driver from %%~nxI ...
    pnputil /add-driver "%%~fI" /install /subdirs || echo (pnputil returned non-zero exit)
  )
) else (
  echo [Info] Nordic driver folder not found. If needed, place INF files under: drivers\nordic
  echo        You can obtain these by installing nRF Connect Desktop and copying its driver package.
)

:end
echo.
echo Done. You may need to re-plug devices or reboot for drivers to take effect.
echo.
exit /b 0
