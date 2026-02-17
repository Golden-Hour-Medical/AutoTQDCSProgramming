# Simple GitHub Deploy (No Cloudflare)

## Best simple path
Use GitHub Releases as the update source.

## How it works
`run_auto_production.bat` can now resolve latest release ZIP automatically from GitHub when:
- `AUTOTQ_GITHUB_REPO` is set (example: `your-org/AutoTQDCSProgramming`)
- optional `AUTOTQ_GITHUB_ASSET` is set (default matches `AutoTQProduction`)

It uses the release `tag_name` as update version, so users auto-update on next launch.

## Setup
1. Create a release with a ZIP asset (for example `AutoTQProduction-2026.02.17.zip`)
2. On user machine (or golden image), set:
   ```cmd
   setx AUTOTQ_GITHUB_REPO "your-org/AutoTQDCSProgramming"
   setx AUTOTQ_GITHUB_ASSET "AutoTQProduction"
   ```
3. Users double-click `run_auto_production.bat`

## Private repo note
Private GitHub release assets require auth.
If repo is private, also set:
```cmd
setx AUTOTQ_GITHUB_TOKEN "ghp_..."
```
This token is sensitive; do not hardcode into distributed scripts.

## Security reality
- Public repo + no token = easiest.
- Private repo + token = still possible, but token management is an operational burden.
- Password-only without account/token requires a gate service (Cloudflare or your backend).
