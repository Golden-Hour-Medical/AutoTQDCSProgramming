@echo off
setlocal EnableDelayedExpansion
set PYTHONUTF8=1
set SSL_CERT_FILE=
set REQUESTS_CA_BUNDLE=

echo.
echo ============================================================
echo   AutoTQ Authentication Check
echo ============================================================
echo.

:: Find Python - prefer venv, fall back to system python
set PYTHON=
if exist ".\.venv\Scripts\python.exe" (
    set PYTHON=.\.venv\Scripts\python.exe
    echo [INFO] Using virtual environment Python
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set PYTHON=python
        echo [INFO] Using system Python
    ) else (
        where py >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set PYTHON=py
            echo [INFO] Using py launcher
        )
    )
)

if "%PYTHON%"=="" (
    echo [ERROR] Python not found!
    echo.
    echo Please either:
    echo   1. Run setup_all.bat to create virtual environment
    echo   2. Install Python 3.8+ and add to PATH
    echo.
    pause
    exit /b 1
)

echo [Step 1] Checking current authentication...
echo ------------------------------------------------------------
%PYTHON% autotq_check_auth.py
set AUTH_RESULT=%ERRORLEVEL%

if %AUTH_RESULT% equ 0 (
    echo.
    echo ============================================================
    echo   SUCCESS - You are already authenticated!
    echo ============================================================
    exit /b 0
)

echo.
echo [Step 2] Authentication failed. Starting login process...
echo ------------------------------------------------------------
echo.
%PYTHON% autotq_login.py
set LOGIN_RESULT=%ERRORLEVEL%

if %LOGIN_RESULT% neq 0 (
    echo.
    echo ============================================================
    echo   ERROR - Login failed. Please try again.
    echo ============================================================
    exit /b 1
)

echo.
echo [Step 3] Verifying new API key...
echo ------------------------------------------------------------
%PYTHON% autotq_check_auth.py
set VERIFY_RESULT=%ERRORLEVEL%

if %VERIFY_RESULT% equ 0 (
    echo.
    echo ============================================================
    echo   SUCCESS - Authentication complete!
    echo   Your API key is saved and ready to use.
    echo ============================================================
    exit /b 0
) else (
    echo.
    echo ============================================================
    echo   ERROR - Verification failed. Please check your setup.
    echo ============================================================
    exit /b 1
)
