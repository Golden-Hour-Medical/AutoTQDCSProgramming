# Create Desktop Shortcut for AutoTQ Production Station

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "AutoTQ Production Station.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = Join-Path $scriptDir "run_auto_production.bat"
$Shortcut.WorkingDirectory = $scriptDir
$Shortcut.Description = "AutoTQ Production Station - Automated Device Flashing"
$Shortcut.IconLocation = "shell32.dll,137"  # Folder icon
$Shortcut.Save()

Write-Host "✅ Shortcut created successfully!" -ForegroundColor Green
Write-Host "   Location: $shortcutPath" -ForegroundColor Cyan

