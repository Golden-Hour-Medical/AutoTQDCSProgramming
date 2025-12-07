<#
.SYNOPSIS
    Runs the AutoTQ Production Station.
.DESCRIPTION
    Robustly finds Python, ensures dependencies are installed, and launches the production script.
#>

$ErrorActionPreference = "Stop"

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "⚡ Starting AutoTQ Production Station" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# ----------------------------------------------------
# 1. DETECT PYTHON (Robust Method)
# ----------------------------------------------------
$pyExe = $null

# A) Check for Virtual Environment first
if (Test-Path ".\.venv\Scripts\python.exe") {
    $pyExe = ".\.venv\Scripts\python.exe"
    Write-Host "[INFO] Using virtual environment: $pyExe" -ForegroundColor Gray
}

# B) Check for 'py' launcher
if (-not $pyExe) {
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        # Check if it works
        try {
            py -3 --version | Out-Null
            $pyExe = "py"
            $pyArgs = @("-3") # Use python 3
            Write-Host "[INFO] Using Python Launcher 'py'" -ForegroundColor Gray
        } catch {}
    }
}

# C) Check standard paths
if (-not $pyExe) {
    $commonPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            $pyExe = $path
            Write-Host "[INFO] Found Python at $path" -ForegroundColor Gray
            break
        }
    }
}

# D) Check PATH
if (-not $pyExe) {
    if (Get-Command "python" -ErrorAction SilentlyContinue) {
        $pyExe = "python"
        Write-Host "[INFO] Found Python in PATH" -ForegroundColor Gray
    }
}

# ----------------------------------------------------
# 2. PYTHON NOT FOUND - EXIT
# ----------------------------------------------------
if (-not $pyExe) {
    Write-Host "`n❌ Python not found!" -ForegroundColor Red
    Write-Host "Please install Python 3.8+ from python.org or the Microsoft Store." -ForegroundColor Yellow
    
    # Optional: Try winget
    if (Get-Command "winget" -ErrorAction SilentlyContinue) {
        $choice = Read-Host "Attempt automatic installation via Winget? (Y/N)"
        if ($choice -eq 'Y' -or $choice -eq 'y') {
            Write-Host "📦 Installing Python 3.11..." -ForegroundColor Cyan
            winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Installed! Please restart this script." -ForegroundColor Green
                exit
            }
        }
    }
    
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# ----------------------------------------------------
# 3. INSTALL DEPENDENCIES
# ----------------------------------------------------
Write-Host "`n📦 Checking dependencies..." -ForegroundColor Cyan

# Construct command args
# Note: & operator needs specific handling for args
if ($pyExe -eq "py") {
    $installCmd = "py"
    $installArgs = @("-3", "-m", "pip", "install", "-r", "requirements.txt")
} else {
    $installCmd = $pyExe
    $installArgs = @("-m", "pip", "install", "-r", "requirements.txt")
}

try {
    & $installCmd $installArgs | Out-Null
    Write-Host "✅ Dependencies verified." -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install dependencies." -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# ----------------------------------------------------
# 4. RUN SCRIPT
# ----------------------------------------------------
Write-Host "`n🚀 Launching Production Station..." -ForegroundColor Green
Write-Host "---------------------------------------------------" -ForegroundColor Gray

# Pass all script arguments through
if ($pyExe -eq "py") {
    & py -3 autotq_auto_production.py $args
} else {
    & $pyExe autotq_auto_production.py $args
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n⚠️ Script exited with error code $LASTEXITCODE" -ForegroundColor Yellow
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
