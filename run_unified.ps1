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

# Invoke unified tool with portable venv
& .\.venv\Scripts\python.exe autotq_unified_production.py $apiKeyArg @args
