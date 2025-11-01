$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:SSL_CERT_FILE = ""
$env:REQUESTS_CA_BUNDLE = ""

Write-Host "========================================"
Write-Host "AutoTQ Bulk Audio Transfer Tool"
Write-Host "========================================"
Write-Host ""
Write-Host "This tool will detect all connected AutoTQ devices"
Write-Host "and transfer audio files to all of them simultaneously."
Write-Host ""
Write-Host "Usage examples:"
Write-Host "  .\run_bulk_audio.ps1                  - Normal mode with prompts"
Write-Host "  .\run_bulk_audio.ps1 --no-prompt      - Start immediately without confirmation"
Write-Host "  .\run_bulk_audio.ps1 --speed ultrafast - Use fastest transfer speed"
Write-Host "  .\run_bulk_audio.ps1 --continuous     - Keep running and detect new devices"
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run setup_all.bat first."
    Read-Host "Press Enter to exit"
    exit 1
}

# Run the bulk audio transfer script
& .\.venv\Scripts\python.exe autotq_bulk_audio_transfer.py @args

# Pause if error occurred
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Read-Host "Press Enter to exit"
}

