# One-Click Private Deployment (No Git Account for End Users)

## What users do
1. Double-click `run_auto_production.bat`
2. Enter one password
3. Wait for auto-download + install + launch

No terminal, no Git commands.

## Important GitHub constraint
Private GitHub releases/repositories require GitHub authentication (token/login).
If you need password-only access without Git accounts, use a small password gate service that returns a temporary ZIP URL.

## Recommended architecture
1. Build/package app ZIP (repo contents that include `install_and_run.bat`)
2. Upload ZIP to private object storage (S3/R2/Azure Blob)
3. Create a tiny HTTPS endpoint that:
   - accepts password
   - validates it server-side
   - returns a short-lived signed URL (`zip_url`)
4. Configure launcher with gate URL:
   - set env var `AUTOTQ_BOOTSTRAP_GATE_URL`
   - or hardcode it inside `run_auto_production.bat`

## Launcher environment variables
- `AUTOTQ_BOOTSTRAP_GATE_URL`
  - Password gate endpoint returning JSON with `zip_url` (or `url`)
- `AUTOTQ_REPO_ZIP_URL`
  - Direct ZIP URL fallback (useful for internal/non-password deployments)

## Example gate response
```json
{
  "zip_url": "https://storage.example.com/autotq.zip?sig=...&exp=...",
  "version": "2026.02.17.1"
}
```

`version` should change on every new release. The launcher compares it to the locally installed version and only downloads when different.

## Notes
- Keep signed URL expiry short (5-15 minutes).
- Rotate password regularly.
- Keep app authentication/enforcement in your existing backend too (defense in depth).

## Fast start in this repo
Use the ready files:
- `deploy/worker.js`
- `deploy/wrangler.toml.example`
- `deploy/deploy.config.example.ps1`
- `deploy/publish_release.ps1`
- `deploy/SETUP.md`
- `.github/workflows/publish-private-release.yml`
- `SIMPLE_GITHUB_DEPLOY.md`
