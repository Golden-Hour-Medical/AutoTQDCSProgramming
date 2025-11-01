$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:SSL_CERT_FILE = ""
$env:REQUESTS_CA_BUNDLE = ""

# Optional API key from file
$apiKeyArg = ""
if (Test-Path .\.autotq_api_key) {
    $key = Get-Content .\.autotq_api_key -Raw
    if ($key) { $apiKeyArg = "--api-key $key" }
}

# Usage examples:
#   .\run_unified.ps1                    - Normal mode with prompts
#   .\run_unified.ps1 --auto-proceed     - Auto-proceed on all prompts (including audio)
#   .\run_unified.ps1 -y                 - Same as --auto-proceed (shorthand)
#   .\run_unified.ps1 --skip-audio       - Skip audio transfer (still prompts for other steps)
#   .\run_unified.ps1 -y --skip-audio    - Auto-proceed but skip audio files

# Invoke unified tool with portable venv
& .\.venv\Scripts\python.exe autotq_unified_production.py $apiKeyArg @args
