# Packaging Guide (Windows Portable Venv)

## Build (on your build machine)

1) Create venv and install deps:
```
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt ppk2_api
```

Optional (plotting overlays):
```
.\.venv\Scripts\pip install matplotlib
```

2) Ensure launcher scripts exist:
- `run_unified.bat` (cmd)
- `run_unified.ps1` (PowerShell)

3) Optional: include `.autotq_api_key` with your key for zero prompts.

4) Clean caches (optional): remove `__pycache__/` dirs.

5) Zip the folder (include `.venv`, `firmware/`, `audio/`, scripts).

## Operator Usage

- Unzip to any folder (e.g., `C:\AutoTQ`).
- Plug PPK2 and AutoTQ PCB via USB.
- Double-click `run_unified.bat` or run:
```
run_unified.bat --api-key YOUR_KEY
```
- The tool will verify/download files, flash firmware, transfer audio, and run tests.

## Notes
- Drivers: include CP210x/CH340/FTDI and PPK2 drivers if needed on clean PCs.
- Offline stations: pre-populate `firmware/` and `audio/`; unified tool will skip downloads.
- Updates: replace zip contents; venv remains self-contained.
