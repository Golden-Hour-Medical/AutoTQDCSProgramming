$BucketName = "autotq-releases"
$AccountId = "YOUR_CLOUDFLARE_ACCOUNT_ID"
$R2AccessKeyId = "YOUR_R2_ACCESS_KEY_ID"
$R2SecretAccessKey = "YOUR_R2_SECRET_ACCESS_KEY"
$ObjectPrefix = "releases"

# Full gate endpoint used by launcher, including /resolve
$GateResolveUrl = "https://autotq-gate.YOUR_SUBDOMAIN.workers.dev/resolve"

# Optional defaults for automatic worker update
$WranglerConfig = "deploy/wrangler.toml"
