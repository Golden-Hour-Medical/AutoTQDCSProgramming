Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = oWS.SpecialFolders("Desktop") & "\AutoTQ Production Station.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = WScript.Arguments(0) & "\run_auto_production.bat"
oLink.WorkingDirectory = WScript.Arguments(0)
oLink.Description = "AutoTQ Production Station - Automated Device Flashing"
oLink.IconLocation = "shell32.dll,137"
oLink.Save
WScript.Echo "Shortcut created on Desktop!"

