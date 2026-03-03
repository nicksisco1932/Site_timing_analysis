@echo off
setlocal

set SITE=Stanford_064
set YEARS=All

python "%~dp0\tulsa_timing.py" --site %SITE% --years %YEARS%

endlocal
