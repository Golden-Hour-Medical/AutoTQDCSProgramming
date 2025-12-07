<#
.SYNOPSIS
    Runs the AutoTQ Production Station.
.DESCRIPTION
    Checks for Python, ensures dependencies are installed, and launches the production script.
#>

Write-Host "⚡ Starting AutoTQ Production Station..." -ForegroundColor Cyan

# Check for Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python not found! Please install Python 3.8+ and add it to PATH." -ForegroundColor Red
    Pause
    Exit 1
}

# Check for pip
if (-not (Get-Command "pip" -ErrorAction SilentlyContinue)) {
    Write-Host "⚠️ 'pip' not found. Trying 'python -m pip'..." -ForegroundColor Yellow
}

# Install/Update Dependencies
Write-Host "📦 Checking dependencies..." -ForegroundColor Gray
try {
    python -m pip install -r requirements.txt | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Pip install failed"
    }
    Write-Host "✅ Dependencies verified." -ForegroundColor Green
}
catch {
    Write-Host "❌ Failed to install dependencies. Check your internet connection." -ForegroundColor Red
    Pause
    Exit 1
}

# Run the script
Write-Host "🚀 Launching Production Station..." -ForegroundColor Green
python autotq_auto_production.py $args

if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ Script exited with error code $LASTEXITCODE" -ForegroundColor Yellow
    Pause
}

