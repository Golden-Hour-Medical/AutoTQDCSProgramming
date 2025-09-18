@echo off
setlocal

if not exist .\.venv\Scripts\python.exe (
  echo [ERROR] Portable venv not found. Run setup_all.bat first.
  exit /b 1
)

set API_ARG=
if exist .autotq_api_key (
  for /f "usebackq delims=" %%A in (".autotq_api_key") do set API_ARG=--api-key %%A
)

.\.venv\Scripts\python.exe pcb_stage_report.py %API_ARG% %*
