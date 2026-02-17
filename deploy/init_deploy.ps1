param(
    [string]$ConfigOut = "deploy/deploy.config.ps1",
    [string]$WranglerOut = "deploy/wrangler.toml"
)

$ErrorActionPreference = "Stop"

function Prompt-Required {
    param([string]$Message, [string]$Default = "")
    while ($true) {
        if ($Default) {
            $value = Read-Host "$Message [$Default]"
            if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
        } else {
            $value = Read-Host $Message
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value.Trim() }
        Write-Host "Value required." -ForegroundColor Yellow
    }
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

Write-Host "AutoTQ Deploy Init" -ForegroundColor Cyan
Write-Host ""

$workerName = Prompt-Required "Worker name" "autotq-gate"
$bucketName = Prompt-Required "R2 bucket name" "autotq-releases"
$accountId = Prompt-Required "Cloudflare account id"
$workerDomain = Prompt-Required "Worker domain (example: autotq-gate.your-subdomain.workers.dev)"
$r2Key = Prompt-Required "R2 access key id"
$r2Secret = Prompt-Required "R2 secret access key"

$gateResolveUrl = "https://$workerDomain/resolve"

$configText = @"
`$BucketName = "$bucketName"
`$AccountId = "$accountId"
`$R2AccessKeyId = "$r2Key"
`$R2SecretAccessKey = "$r2Secret"
`$ObjectPrefix = "releases"
`$GateResolveUrl = "$gateResolveUrl"
`$WranglerConfig = "deploy/wrangler.toml"
"@

$wranglerText = @"
name = "$workerName"
main = "worker.js"
compatibility_date = "2025-12-01"

[vars]
URL_TTL_SECONDS = "900"

[[r2_buckets]]
binding = "RELEASES"
bucket_name = "$bucketName"
"@

Set-Content -Path $ConfigOut -Value $configText -NoNewline
Set-Content -Path $WranglerOut -Value $wranglerText -NoNewline

$suggestedSigningSecret = New-RandomSecret

Write-Host ""
Write-Host "Wrote $ConfigOut and $WranglerOut" -ForegroundColor Green
Write-Host ""
Write-Host "Next commands:"
Write-Host "1) wrangler secret put ACCESS_PASSWORD --config deploy/wrangler.toml"
Write-Host "2) wrangler secret put SIGNING_SECRET --config deploy/wrangler.toml"
Write-Host "   Suggested SIGNING_SECRET:"
Write-Host "   $suggestedSigningSecret"
Write-Host "3) .\deploy\publish_release.ps1 -ConfigPath deploy/deploy.config.ps1 -UpdateWorker"
Write-Host "4) setx AUTOTQ_BOOTSTRAP_GATE_URL `"$gateResolveUrl`""
