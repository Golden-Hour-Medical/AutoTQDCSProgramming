@echo off
setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo   AutoTQ Authentication Check
echo ============================================================
echo.

:: Find Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.8+
    exit /b 1
)

echo [Step 1] Checking current authentication...
echo ------------------------------------------------------------
python autotq_check_auth.py
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
python autotq_login.py
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
python autotq_check_auth.py
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

