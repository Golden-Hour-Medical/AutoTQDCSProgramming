@echo off
setlocal

REM Check for help request
if "%1"=="-h" goto :show_help
if "%1"=="--help" goto :show_help
if "%1"=="/?" goto :show_help

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

REM Process arguments to handle --no-humidity option
set ARGS=
set NO_HUMIDITY=0

:parse_args
if "%1"=="" goto :run_program
if "%1"=="--no-humidity" (
  set NO_HUMIDITY=1
  shift
  goto :parse_args
)
set ARGS=%ARGS% %1
shift
goto :parse_args

:run_program
REM Add --rh 0 if --no-humidity was specified
if %NO_HUMIDITY%==1 (
  echo [INFO] Running with humidity control disabled (--rh 0)
  .\.venv\Scripts\python.exe autotq_cycling_stage.py --rh 0 %ARGS%
) else (
  echo [INFO] Running with default smart humidity control (--rh 45)
  .\.venv\Scripts\python.exe autotq_cycling_stage.py %ARGS%
)
goto :end

:show_help
echo AutoTQ Cycling Stage Controller - Batch Wrapper
echo.
echo Usage: run_cycling.bat [OPTIONS]
echo.
echo Batch-specific options:
echo   --no-humidity     Disable all humidity control (sets --rh 0)
echo   -h, --help, /?    Show this help
echo.
echo All other options are passed to autotq_cycling_stage.py:
echo   --cycles N        Number of thermal cycles (default: 3)
echo   --rt TEMP         Room temperature setpoint (default: 25.0)
echo   --hi TEMP         High temperature setpoint (default: 60.0)
echo   --lo TEMP         Low temperature setpoint (default: -20.0)
echo   --rh PERCENT      Humidity percentage (default: 45, auto-adjusts by temp)
echo   --tol TEMP        Temperature tolerance (default: 0.5)
echo.
echo Examples:
echo   run_cycling.bat                    ^(default: 3 cycles with smart humidity^)
echo   run_cycling.bat --no-humidity     ^(disable humidity control^)
echo   run_cycling.bat --cycles 5        ^(5 cycles with smart humidity^)
echo   run_cycling.bat --no-humidity --cycles 10  ^(10 cycles, no humidity^)
echo.

:end
