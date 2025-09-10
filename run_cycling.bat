@echo off
setlocal

REM Ensure venv exists
if not exist .\.venv\Scripts\python.exe (
  echo [ERROR] Portable venv not found. Run setup_all.bat first.
  exit /b 1
)

REM Ensure pyvisa is available (quiet install if missing)
.\.venv\Scripts\python -c "import pyvisa" >nul 2>&1 || (
  echo Installing pyvisa into portable venv...
  .\.venv\Scripts\pip install --no-input pyvisa || (
    echo [WARNING] Failed to install pyvisa automatically.
  )
)

REM Run the cycling stage tool (pass through arguments)
.\.venv\Scripts\python.exe autotq_cycling_stage.py %*
