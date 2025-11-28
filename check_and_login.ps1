# AutoTQ Authentication Check and Login Script
# PowerShell version

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:SSL_CERT_FILE = ""
$env:REQUESTS_CA_BUNDLE = ""

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  AutoTQ Authentication Check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Find Python - prefer venv, fall back to system python
$python = $null

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
    Write-Host "[INFO] Using virtual environment Python" -ForegroundColor Gray
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = "python"
        Write-Host "[INFO] Using system Python" -ForegroundColor Gray
    } else {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            $python = "py"
            Write-Host "[INFO] Using py launcher" -ForegroundColor Gray
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

# Step 1: Check current authentication
Write-Host "[Step 1] Checking current authentication..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------------" -ForegroundColor Gray
& $python autotq_check_auth.py
$authResult = $LASTEXITCODE

if ($authResult -eq 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  SUCCESS - You are already authenticated!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    exit 0
}

# Step 2: Run login
Write-Host ""
Write-Host "[Step 2] Authentication failed. Starting login process..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------------" -ForegroundColor Gray
Write-Host ""
& $python autotq_login.py
$loginResult = $LASTEXITCODE

if ($loginResult -ne 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  ERROR - Login failed. Please try again." -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    exit 1
}

# Step 3: Verify new authentication
Write-Host ""
Write-Host "[Step 3] Verifying new API key..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------------" -ForegroundColor Gray
& $python autotq_check_auth.py
$verifyResult = $LASTEXITCODE

if ($verifyResult -eq 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  SUCCESS - Authentication complete!" -ForegroundColor Green
    Write-Host "  Your API key is saved and ready to use." -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  ERROR - Verification failed. Please check your setup." -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    exit 1
}
