@echo off
setlocal
set PYTHONUTF8=1
set SSL_CERT_FILE=
set REQUESTS_CA_BUNDLE=

REM Optional: read API key from file if present
set APIKEY_FILE=.autotq_api_key
set API_ARG=
if exist %APIKEY_FILE% (
  for /f "usebackq delims=" %%A in ("%APIKEY_FILE%") do set API_ARG=--api-key %%A
)

REM Pass through user args; if API key file exists and user didn't pass --api-key, include it
.\.venv\Scripts\python.exe autotq_unified_production.py %API_ARG% %*
