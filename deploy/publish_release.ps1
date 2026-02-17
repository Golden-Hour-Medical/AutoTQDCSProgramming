param(
    [string]$ConfigPath = "deploy/deploy.config.ps1",
    [string]$Version = "",
    [switch]$UpdateWorker
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

if (-not (Test-Path $ConfigPath)) {
    throw "Config file not found: $ConfigPath (copy deploy/deploy.config.example.ps1 to deploy/deploy.config.ps1 and fill values)"
}

. $ConfigPath

if (-not $BucketName) { throw "BucketName missing in config" }
if (-not $AccountId) { throw "AccountId missing in config" }
if (-not $R2AccessKeyId) { throw "R2AccessKeyId missing in config" }
if (-not $R2SecretAccessKey) { throw "R2SecretAccessKey missing in config" }
if (-not $ObjectPrefix) { $ObjectPrefix = "releases" }

Require-Command "aws"
Require-Command "robocopy"

if (-not $Version) {
    $Version = Get-Date -Format "yyyy.MM.dd.HHmmss"
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$stagingDir = Join-Path $env:TEMP "autotq_release_staging_$Version"
$zipName = "AutoTQProduction-$Version.zip"
$zipPath = Join-Path $env:TEMP $zipName
$objectKey = "$ObjectPrefix/$zipName"
$endpoint = "https://$AccountId.r2.cloudflarestorage.com"

if (Test-Path $stagingDir) {
    Remove-Item -Recurse -Force $stagingDir
}
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
New-Item -ItemType Directory -Path $stagingDir | Out-Null

Write-Host "Staging files..."
$excludeDirs = @(
    ".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".idea", ".vscode"
)
$excludeFiles = @(
    "autotq_token.json", ".autotq_api_key", "autotq_api_key.txt", "autotq_setup.log", "session_log_*.csv"
)

$robocopyArgs = @(
    $projectRoot.Path, $stagingDir,
    "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
)
foreach ($d in $excludeDirs) { $robocopyArgs += @("/XD", $d) }
foreach ($f in $excludeFiles) { $robocopyArgs += @("/XF", $f) }

& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

Write-Host "Creating ZIP: $zipPath"
Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force

Write-Host "Uploading to R2: s3://$BucketName/$objectKey"
$env:AWS_ACCESS_KEY_ID = $R2AccessKeyId
$env:AWS_SECRET_ACCESS_KEY = $R2SecretAccessKey
$env:AWS_DEFAULT_REGION = "auto"

& aws s3 cp $zipPath "s3://$BucketName/$objectKey" --endpoint-url $endpoint --no-progress
if ($LASTEXITCODE -ne 0) {
    throw "aws upload failed with exit code $LASTEXITCODE"
}

if ($UpdateWorker) {
    Require-Command "wrangler"
    if (-not $WranglerConfig) { $WranglerConfig = "deploy/wrangler.toml" }
    Write-Host "Updating worker vars via wrangler deploy..."
    & wrangler deploy --config $WranglerConfig --var "CURRENT_VERSION=$Version" --var "CURRENT_OBJECT_KEY=$objectKey"
    if ($LASTEXITCODE -ne 0) {
        throw "wrangler deploy failed with exit code $LASTEXITCODE"
    }
}

Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Release published successfully."
Write-Host "Version: $Version"
Write-Host "Object key: $objectKey"
if ($GateResolveUrl) {
    Write-Host "Set launcher env var:"
    Write-Host "  setx AUTOTQ_BOOTSTRAP_GATE_URL `"$GateResolveUrl`""
}
Write-Host ""
Write-Host "If you did not use -UpdateWorker, update worker vars manually:"
Write-Host "  CURRENT_VERSION=$Version"
Write-Host "  CURRENT_OBJECT_KEY=$objectKey"
