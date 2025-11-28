# AutoTQ Production Tools Menu
# PowerShell version with colors

$env:PYTHONUTF8 = "1"
$env:SSL_CERT_FILE = ""
$env:REQUESTS_CA_BUNDLE = ""

# Find Python - prefer venv, fall back to system python
$python = $null

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = "python"
    } else {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            $python = "py"
        }
    }
}

if (-not $python) {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please either:" -ForegroundColor Yellow
    Write-Host "  1. Run setup_all.bat to create virtual environment"
    Write-Host "  2. Install Python 3.8+ and add to PATH"
    Write-Host ""
    exit 1
}

function Show-Menu {
    Clear-Host
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "  |                                                          |" -ForegroundColor Cyan
    Write-Host "  |              AutoTQ Production Tools Menu                 |" -ForegroundColor Cyan
    Write-Host "  |                                                          |" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "AUTHENTICATION" -ForegroundColor Yellow -NoNewline; Write-Host " ----------------------"
    Write-Host ""
    Write-Host "    [1]  " -NoNewline -ForegroundColor Green; Write-Host "Check Authentication"
    Write-Host "         Check if your API key is valid and working" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [2]  " -NoNewline -ForegroundColor Green; Write-Host "Login & Generate API Key"
    Write-Host "         Login with username/password to create a new API key" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [3]  " -NoNewline -ForegroundColor Green; Write-Host "Check & Login (Auto)"
    Write-Host "         Check auth first, login only if needed" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "FULL WORKFLOWS" -ForegroundColor Yellow -NoNewline; Write-Host " ----------------------"
    Write-Host ""
    Write-Host "    [4]  " -NoNewline -ForegroundColor Green; Write-Host "Full Production Flow " -NoNewline; Write-Host "(Recommended)" -ForegroundColor Magenta
    Write-Host "         Complete workflow: firmware + audio + register device" -ForegroundColor Gray
    Write-Host "         Includes PPK2 power, testing, and database registration" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [5]  " -NoNewline -ForegroundColor Green; Write-Host "Setup & Program (Simple)"
    Write-Host "         Download latest files and program single device" -ForegroundColor Gray
    Write-Host "         Firmware + audio transfer" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [6]  " -NoNewline -ForegroundColor Green; Write-Host "Setup Only"
    Write-Host "         Download/update firmware and audio files from server" -ForegroundColor Gray
    Write-Host "         Does NOT program any devices" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "FIRMWARE ONLY" -ForegroundColor Yellow -NoNewline; Write-Host " -----------------------"
    Write-Host ""
    Write-Host "    [7]  " -NoNewline -ForegroundColor Green; Write-Host "Flash Firmware Only"
    Write-Host "         Flash firmware to a single device (no audio)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [8]  " -NoNewline -ForegroundColor Green; Write-Host "Program Device (Firmware + Audio)"
    Write-Host "         Flash firmware AND transfer audio to single device" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "AUDIO ONLY" -ForegroundColor Yellow -NoNewline; Write-Host " --------------------------"
    Write-Host ""
    Write-Host "    [9]  " -NoNewline -ForegroundColor Green; Write-Host "Bulk Audio Transfer (Multiple Devices)"
    Write-Host "         Transfer audio files to many devices in parallel" -ForegroundColor Gray
    Write-Host "         Perfect for production lines" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   [10]  " -NoNewline -ForegroundColor Green; Write-Host "Single Device Audio Transfer"
    Write-Host "         Transfer audio files to one device only" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "DEVICE INFO" -ForegroundColor Yellow -NoNewline; Write-Host " -------------------------"
    Write-Host ""
    Write-Host "   [11]  " -NoNewline -ForegroundColor Green; Write-Host "Show Device Info"
    Write-Host "         Display MAC address, firmware version of connected devices" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   [12]  " -NoNewline -ForegroundColor Green; Write-Host "Check Serial Ports"
    Write-Host "         List all available COM ports and detect AutoTQ devices" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   [13]  " -NoNewline -ForegroundColor Green; Write-Host "Quick Device Check"
    Write-Host "         Fast check of connected device status" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "REPORTS" -ForegroundColor Yellow -NoNewline; Write-Host " -----------------------------"
    Write-Host ""
    Write-Host "   [14]  " -NoNewline -ForegroundColor Green; Write-Host "Generate PCB Report"
    Write-Host "         Create CSV report of PCB test results" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  ---------------------- " -NoNewline; Write-Host "OTHER" -ForegroundColor Yellow -NoNewline; Write-Host " -------------------------------"
    Write-Host ""
    Write-Host "   [15]  " -NoNewline -ForegroundColor Green; Write-Host "Install USB Drivers"
    Write-Host "         Install required USB/serial drivers" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    [0]  " -NoNewline -ForegroundColor Red; Write-Host "Exit"
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Pause-AndReturn {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "  Press any key to return to menu..." -ForegroundColor Yellow
    Write-Host "  ============================================================" -ForegroundColor Cyan
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

function Run-Command {
    param([string]$Title, [string]$Description, [string]$Command)
    
    Clear-Host
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "   $Title" -ForegroundColor White
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
    if ($Description) {
        Write-Host "  $Description" -ForegroundColor Gray
        Write-Host ""
    }
    
    Invoke-Expression $Command
    Pause-AndReturn
}

# Main loop
while ($true) {
    Show-Menu
    $choice = Read-Host "  Enter your choice [0-15]"
    
    switch ($choice) {
        "0" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Goodbye!" -ForegroundColor Green
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            exit 0
        }
        "1" {
            Run-Command "Checking Authentication..." "" "& $python autotq_check_auth.py"
        }
        "2" {
            Run-Command "Login & Generate API Key" "" "& $python autotq_login.py"
        }
        "3" {
            Run-Command "Check & Login (Auto)" "" "& .\check_and_login.ps1"
        }
        "4" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Full Production Flow" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will:" -ForegroundColor Yellow
            Write-Host "    - Check/download latest firmware and audio" -ForegroundColor Gray
            Write-Host "    - Configure PPK2 power supply (4.2V)" -ForegroundColor Gray
            Write-Host "    - Flash firmware to device" -ForegroundColor Gray
            Write-Host "    - Transfer audio files" -ForegroundColor Gray
            Write-Host "    - Register device in database" -ForegroundColor Gray
            Write-Host "    - Run production tests" -ForegroundColor Gray
            Write-Host ""
            Write-Host "  Press Ctrl+C to cancel, or press Enter to continue..." -ForegroundColor Yellow
            Read-Host
            & $python autotq_unified_production.py
            Pause-AndReturn
        }
        "5" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Setup & Program" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will:" -ForegroundColor Yellow
            Write-Host "    - Download latest firmware and audio files" -ForegroundColor Gray
            Write-Host "    - Flash firmware to connected device" -ForegroundColor Gray
            Write-Host "    - Transfer audio files" -ForegroundColor Gray
            Write-Host ""
            Read-Host "  Press Enter to continue..."
            & .\setup_and_program.bat
            Pause-AndReturn
        }
        "6" {
            Run-Command "Setup Only (Download Files)" "Downloading latest firmware and audio files from server..." "& $python autotq_setup.py"
        }
        "7" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Flash Firmware Only" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will flash firmware to the connected device." -ForegroundColor Yellow
            Write-Host "  Audio files will NOT be transferred." -ForegroundColor Gray
            Write-Host ""
            Read-Host "  Press Enter to continue..."
            & $python autotq_firmware_programmer.py
            Pause-AndReturn
        }
        "8" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Program Device (Firmware + Audio)" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will:" -ForegroundColor Yellow
            Write-Host "    - Flash firmware to device" -ForegroundColor Gray
            Write-Host "    - Transfer all audio files" -ForegroundColor Gray
            Write-Host ""
            Read-Host "  Press Enter to continue..."
            & $python autotq_programmer.py
            Pause-AndReturn
        }
        "9" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Bulk Audio Transfer (Multiple Devices)" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will transfer audio files to ALL connected AutoTQ devices" -ForegroundColor Yellow
            Write-Host "  simultaneously using parallel threads." -ForegroundColor Gray
            Write-Host ""
            Write-Host "  Connect multiple devices before continuing." -ForegroundColor Magenta
            Write-Host ""
            Read-Host "  Press Enter to continue..."
            & $python autotq_bulk_audio_transfer.py
            Pause-AndReturn
        }
        "10" {
            Clear-Host
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host "   Single Device Audio Transfer" -ForegroundColor White
            Write-Host "  ============================================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  This will transfer audio files to ONE device." -ForegroundColor Yellow
            Write-Host ""
            Read-Host "  Press Enter to continue..."
            & $python autotq_programmer.py --audio-only
            Pause-AndReturn
        }
        "11" {
            Run-Command "Device Information" "" "& $python autotq_device_info.py"
        }
        "12" {
            Run-Command "Check Serial Ports" "" "& $python check_port.py"
        }
        "13" {
            Run-Command "Quick Device Check" "" "& $python autotq_quick_check.py"
        }
        "14" {
            Run-Command "Generate PCB Report" "" "& $python pcb_stage_report.py"
        }
        "15" {
            Run-Command "Install USB Drivers" "" "& .\install_drivers.bat"
        }
        default {
            Write-Host ""
            Write-Host "  [!] Invalid choice. Please try again." -ForegroundColor Red
            Start-Sleep -Seconds 2
        }
    }
}
