@echo off
setlocal ENABLEDELAYEDEXPANSION
title AutoTQ Production Station

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

echo ===================================================
echo Starting AutoTQ Production Station
echo ===================================================

REM ---------------------------------------------------------------------------
REM 0. SELF-BOOTSTRAP (for non-technical users running only this .bat file)
REM ---------------------------------------------------------------------------
if not exist "autotq_auto_production.py" goto :BOOTSTRAP
if not exist "requirements.txt" goto :BOOTSTRAP
goto :LOCAL_RUN

:BOOTSTRAP
echo.
echo [INFO] Core project files were not found next to this launcher.
echo [INFO] Downloading and installing AutoTQ automatically...

set "REPO_ZIP_URL=%AUTOTQ_REPO_ZIP_URL%"
if not defined REPO_ZIP_URL set "REPO_ZIP_URL=https://github.com/YOUR_ORG/AutoTQDCSProgramming/archive/refs/heads/main.zip"
set "BOOTSTRAP_GATE_URL=%AUTOTQ_BOOTSTRAP_GATE_URL%"
set "GITHUB_REPO=%AUTOTQ_GITHUB_REPO%"
set "GITHUB_ASSET=%AUTOTQ_GITHUB_ASSET%"
if not defined GITHUB_ASSET set "GITHUB_ASSET=AutoTQProduction"
set "REMOTE_VERSION="

if defined BOOTSTRAP_GATE_URL (
    set "RESOLVED_URL_FILE=%TEMP%\autotq_repo_zip_url.txt"
    set "RESOLVED_VERSION_FILE=%TEMP%\autotq_repo_version.txt"
    del "%RESOLVED_URL_FILE%" >nul 2>&1
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
    echo.
    echo [INFO] This installer is password protected.
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference='Stop'; $pw=Read-Host 'Enter access password'; if([string]::IsNullOrWhiteSpace($pw)){throw 'Password is required'}; $body=@{password=$pw}|ConvertTo-Json -Compress; $resp=Invoke-RestMethod -Method Post -Uri '%BOOTSTRAP_GATE_URL%' -ContentType 'application/json' -Body $body; $url=$resp.zip_url; if(-not $url){$url=$resp.url}; if(-not $url){throw 'Response missing zip_url/url'}; $ver=$resp.version; if(-not $ver){$ver=$resp.etag}; if(-not $ver){$ver='always-download'}; Set-Content -Path '%RESOLVED_URL_FILE%' -Value $url -NoNewline; Set-Content -Path '%RESOLVED_VERSION_FILE%' -Value $ver -NoNewline"
    if errorlevel 1 (
        echo.
        echo [ERROR] Password validation failed or bootstrap URL could not be resolved.
        pause
        goto :END_FAIL
    )

    for /f "usebackq delims=" %%U in ("%RESOLVED_URL_FILE%") do set "REPO_ZIP_URL=%%U"
    for /f "usebackq delims=" %%V in ("%RESOLVED_VERSION_FILE%") do set "REMOTE_VERSION=%%V"
    del "%RESOLVED_URL_FILE%" >nul 2>&1
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
)

if not defined BOOTSTRAP_GATE_URL if "%REPO_ZIP_URL%"=="https://github.com/YOUR_ORG/AutoTQDCSProgramming/archive/refs/heads/main.zip" if defined GITHUB_REPO (
    set "RESOLVED_URL_FILE=%TEMP%\autotq_repo_zip_url.txt"
    set "RESOLVED_VERSION_FILE=%TEMP%\autotq_repo_version.txt"
    del "%RESOLVED_URL_FILE%" >nul 2>&1
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference='Stop'; $headers=@{}; if($env:AUTOTQ_GITHUB_TOKEN){$headers['Authorization']='Bearer ' + $env:AUTOTQ_GITHUB_TOKEN; $headers['Accept']='application/vnd.github+json'}; $api='https://api.github.com/repos/' + $env:AUTOTQ_GITHUB_REPO + '/releases/latest'; $rel=Invoke-RestMethod -Method Get -Headers $headers -Uri $api; $asset=$null; if($env:AUTOTQ_GITHUB_ASSET){ $asset=$rel.assets | Where-Object { $_.name -like ('*' + $env:AUTOTQ_GITHUB_ASSET + '*') -and $_.name -like '*.zip' } | Select-Object -First 1 }; if(-not $asset){ $asset=$rel.assets | Where-Object { $_.name -like '*.zip' } | Select-Object -First 1 }; if(-not $asset){ throw 'No ZIP asset found in latest release' }; $url=$asset.browser_download_url; $ver=$rel.tag_name; if(-not $ver){$ver=$asset.updated_at}; if(-not $ver){$ver='always-download'}; Set-Content -Path '%RESOLVED_URL_FILE%' -Value $url -NoNewline; Set-Content -Path '%RESOLVED_VERSION_FILE%' -Value $ver -NoNewline"
    if not errorlevel 1 (
        for /f "usebackq delims=" %%U in ("%RESOLVED_URL_FILE%") do set "REPO_ZIP_URL=%%U"
        for /f "usebackq delims=" %%V in ("%RESOLVED_VERSION_FILE%") do set "REMOTE_VERSION=%%V"
    )
    del "%RESOLVED_URL_FILE%" >nul 2>&1
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
)

if "%REPO_ZIP_URL%"=="https://github.com/YOUR_ORG/AutoTQDCSProgramming/archive/refs/heads/main.zip" (
    echo.
    echo [ERROR] Launcher is not configured with a real download source yet.
    echo         Configure one of these:
    echo         1) Set AUTOTQ_REPO_ZIP_URL (direct zip URL), or
    echo         2) Set AUTOTQ_BOOTSTRAP_GATE_URL (password gate endpoint)
    echo         3) Set AUTOTQ_GITHUB_REPO (public/private releases)
    echo         or replace the placeholder directly in:
    echo         %~f0
    echo.
    pause
    goto :END_FAIL
)

set "INSTALL_ROOT=%LOCALAPPDATA%\AutoTQProduction"
set "ZIP_PATH=%TEMP%\AutoTQProduction.zip"
set "EXTRACT_DIR=%INSTALL_ROOT%\extract"
set "APP_DIR=%INSTALL_ROOT%\app"
set "VERSION_FILE=%INSTALL_ROOT%\installed_source_version.txt"
set "NEED_DOWNLOAD=1"

if not defined REMOTE_VERSION (
    set "RESOLVED_VERSION_FILE=%TEMP%\autotq_repo_version.txt"
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference='Stop'; $h=(Invoke-WebRequest -Method Head -Uri '%REPO_ZIP_URL%').Headers; $v=$h.ETag; if(-not $v){$v=$h.'Last-Modified'}; if(-not $v){$v='always-download'}; Set-Content -Path '%RESOLVED_VERSION_FILE%' -Value $v -NoNewline"
    if not errorlevel 1 (
        for /f "usebackq delims=" %%V in ("%RESOLVED_VERSION_FILE%") do set "REMOTE_VERSION=%%V"
    )
    del "%RESOLVED_VERSION_FILE%" >nul 2>&1
)

if not defined REMOTE_VERSION set "REMOTE_VERSION=always-download"

if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%" >nul 2>&1
if exist "%APP_DIR%\install_and_run.bat" if exist "%VERSION_FILE%" (
    set /p LOCAL_VERSION=<"%VERSION_FILE%"
    if /i "!LOCAL_VERSION!"=="!REMOTE_VERSION!" set "NEED_DOWNLOAD=0"
)

if /i "%REMOTE_VERSION%"=="always-download" set "NEED_DOWNLOAD=1"
if "%NEED_DOWNLOAD%"=="0" goto :RUN_INSTALLED

echo [INFO] New source update detected. Downloading latest package...
if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%REPO_ZIP_URL%' -OutFile '%ZIP_PATH%'"
if errorlevel 1 (
    echo.
    echo [ERROR] Download failed. Check internet access and repository URL.
    pause
    goto :END_FAIL
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to extract downloaded package.
    pause
    goto :END_FAIL
)

del "%ZIP_PATH%" >nul 2>&1

set "RUN_DIR="
for /f "delims=" %%D in ('dir /b /ad "%EXTRACT_DIR%" 2^>nul') do (
    if not defined RUN_DIR set "RUN_DIR=%EXTRACT_DIR%\%%D"
)
if not defined RUN_DIR set "RUN_DIR=%EXTRACT_DIR%"

if not exist "%RUN_DIR%\install_and_run.bat" (
    echo.
    echo [ERROR] install_and_run.bat was not found in downloaded package.
    pause
    goto :END_FAIL
)

if not exist "%APP_DIR%" mkdir "%APP_DIR%" >nul 2>&1
robocopy "%RUN_DIR%" "%APP_DIR%" /E /NFL /NDL /NJH /NJS /NP /XD ".git" ".venv" "__pycache__" >nul
if errorlevel 8 (
    echo.
    echo [ERROR] Failed to copy downloaded files into managed app directory.
    pause
    goto :END_FAIL
)
set "AUTOTQ_REMOTE_VERSION=%REMOTE_VERSION%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Set-Content -Path '%VERSION_FILE%' -Value $env:AUTOTQ_REMOTE_VERSION -NoNewline"

:RUN_INSTALLED
if not exist "%APP_DIR%\install_and_run.bat" (
    echo.
    echo [ERROR] Managed install is incomplete (install_and_run.bat missing).
    pause
    goto :END_FAIL
)
echo [INFO] Running installer from: %APP_DIR%
call "%APP_DIR%\install_and_run.bat" %*
if errorlevel 1 goto :END_FAIL
goto :END_OK

:LOCAL_RUN
REM ---------------------------------------------------------------------------
REM 1. DETECT PYTHON
REM ---------------------------------------------------------------------------
set "PYEXE="
set "VENV_PYTHON=.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -m pip --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYEXE=%VENV_PYTHON%"
        echo [INFO] Using virtual environment
        goto :FOUND
    ) else (
        echo [WARN] Virtual environment corrupted. Recreating...
        rmdir /s /q .venv 2>nul
    )
)

set "SYS_PYTHON="
where py >nul 2>&1
if !errorlevel! equ 0 (
    set "SYS_PYTHON=py"
    echo [INFO] Found py launcher
    goto :HAVE_SYSTEM_PYTHON
)

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)
if exist "C:\Python311\python.exe" (
    set "SYS_PYTHON=C:\Python311\python.exe"
    goto :HAVE_SYSTEM_PYTHON
)

where python >nul 2>&1
if !errorlevel! equ 0 (
    set "SYS_PYTHON=python"
    echo [INFO] Found python in PATH
    goto :HAVE_SYSTEM_PYTHON
)

echo.
echo ERROR: Python not found!
echo Please install Python 3.8+ from python.org
pause
goto :END_FAIL

:HAVE_SYSTEM_PYTHON
echo [INFO] Using: %SYS_PYTHON%

REM ---------------------------------------------------------------------------
REM 2. CREATE VENV IF NEEDED
REM ---------------------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Creating virtual environment...
    %SYS_PYTHON% -m venv .venv
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create virtual environment!
        pause
        goto :END_FAIL
    )
    echo Virtual environment created.
)

set "PYEXE=.venv\Scripts\python.exe"
"%PYEXE%" -m ensurepip --upgrade >nul 2>&1
"%PYEXE%" -m pip install --upgrade pip >nul 2>&1

:FOUND
REM ---------------------------------------------------------------------------
REM 3. INSTALL DEPENDENCIES
REM ---------------------------------------------------------------------------
echo.
echo Checking dependencies...
"%PYEXE%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install dependencies!
    pause
    goto :END_FAIL
)

echo Dependencies OK.

REM ---------------------------------------------------------------------------
REM 4. RUN SCRIPT
REM ---------------------------------------------------------------------------
echo.
echo Launching Production Station...
echo.
"%PYEXE%" autotq_auto_production.py %*
if %errorlevel% neq 0 (
    echo.
    echo Script exited with error.
    pause
    goto :END_FAIL
)
goto :END_OK

:END_OK
popd >nul 2>&1
exit /b 0

:END_FAIL
popd >nul 2>&1
exit /b 1
