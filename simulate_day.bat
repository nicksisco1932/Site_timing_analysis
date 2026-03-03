@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM Monte Carlo simulation of full clinical days for a site
REM -------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set DATE=20251119

REM Simulation parameters
set N_SIM=10000
set CUTOFF=12:00
set ANEST_START=08:00
set ANEST_MIN=20
set PRE_INSERT_GAP_MIN=20
set INSERT_MIN=45

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis
set REPO_ROOT=%~dp0
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

set ANALYSIS_DIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%

echo.
echo ================================================================
echo   DAY SIMULATION (Monte Carlo)
echo   Site:          %SITE%
echo   Date:          %DATE%
echo   Analysis dir:  %ANALYSIS_DIR%
echo   N_sim:         %N_SIM%
echo   Cutoff:        %CUTOFF%
echo   Anest start:   %ANEST_START%
echo   Anest (min):   %ANEST_MIN%
echo   Pre-insert gap:%PRE_INSERT_GAP_MIN%
echo   Insertion (min):%INSERT_MIN%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_day_simulation.py" ^
    --site %SITE% ^
    --analysis-root "%ANALYSIS_DIR%" ^
    --n-sim %N_SIM% ^
    --cutoff "%CUTOFF%" ^
    --anest-start "%ANEST_START%" ^
    --anest-minutes %ANEST_MIN% ^
    --pre-insert-gap-minutes %PRE_INSERT_GAP_MIN% ^
    --insert-minutes %INSERT_MIN%

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Day simulation failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo Day simulation complete.
endlocal
