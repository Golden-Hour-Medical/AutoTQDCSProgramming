@echo off
echo Creating Desktop Shortcut for AutoTQ Production Station...

set "SCRIPT_DIR=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%DESKTOP%\AutoTQ Production Station.lnk'); $Shortcut.TargetPath = '%SCRIPT_DIR%run_auto_production.bat'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.Description = 'AutoTQ Production Station - Automated Device Flashing'; $Shortcut.IconLocation = 'shell32.dll,137'; $Shortcut.Save()"

if %errorlevel% equ 0 (
    echo.
    echo ✅ Shortcut created successfully!
    echo    Location: %DESKTOP%\AutoTQ Production Station.lnk
    echo.
) else (
    echo.
    echo ❌ Failed to create shortcut
    echo.
)

pause

