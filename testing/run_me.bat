@echo off
setlocal

REM Project: Site Timing Analysis
REM File: testing/run_me.bat
REM Primary author: Nicholas J. Sisco, Ph.D.
REM Organization: Profound Medical, LLC
REM Created: 2026-03-03
REM Purpose: Runs the run me timing-analysis workflow from Windows batch.
REM
REM Provenance: Original implementation or material contribution by
REM Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
REM
REM Rights status: Proprietary / internal use unless otherwise specified
REM by Profound Medical, LLC.
set SITE=Stanford_064
set YEARS=All

set REPO_ROOT=%~dp0..\
set PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe

"%PYTHON%" "%~dp0\tulsa_timing.py" --site %SITE% --years %YEARS%

endlocal
