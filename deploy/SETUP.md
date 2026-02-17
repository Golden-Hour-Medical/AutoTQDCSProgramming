# Easy Deploy Setup

This sets up private one-click deployment with password protection and automatic updates.

## One-time setup
1. Install tools:
   - `wrangler` (Cloudflare Workers CLI)
   - `aws` CLI
2. In Cloudflare:
   - Create R2 bucket (example: `autotq-releases`)
   - Create Worker from `deploy/worker.js`
3. Generate config files (wizard):
   - `.\deploy\init_deploy.ps1`
4. Set worker secrets (run once):
   - `wrangler secret put ACCESS_PASSWORD --config deploy/wrangler.toml`
   - `wrangler secret put SIGNING_SECRET --config deploy/wrangler.toml`

## Publish a new release
From repo root:

```powershell
.\deploy\publish_release.ps1 -ConfigPath deploy/deploy.config.ps1 -UpdateWorker
```

What this does:
- Builds a clean ZIP from your repo
- Uploads it to R2
- Updates worker vars `CURRENT_VERSION` and `CURRENT_OBJECT_KEY`

## Configure launcher
Set this once on each production PC image (or hardcode in launcher):

```cmd
setx AUTOTQ_BOOTSTRAP_GATE_URL "https://YOUR_WORKER_DOMAIN/resolve"
```

Your `run_auto_production.bat` will then:
- prompt for password
- resolve private download URL
- auto-download only when `version` changes
- install and run

## Optional: publish from GitHub UI (no local CLI)
This repo includes workflow:
- `.github/workflows/publish-private-release.yml`

Set these repository secrets:
- `CLOUDFLARE_API_TOKEN`
- `CF_ACCOUNT_ID`
- `CF_R2_BUCKET_NAME`
- `CF_R2_ACCESS_KEY_ID`
- `CF_R2_SECRET_ACCESS_KEY`
- `CF_WORKER_NAME`
- `CF_WORKER_DOMAIN` (example: `autotq-gate.your-subdomain.workers.dev`)
- `CF_ACCESS_PASSWORD` (optional auto-sync)
- `CF_SIGNING_SECRET` (optional auto-sync)

Then run:
1. GitHub -> Actions -> `Publish Private Release`
2. Click `Run workflow`
3. Optional version input, keep `update_worker=true`
