@echo off
rem ==========================================================================
rem  Clipper - run the automated tests (no internet needed)
rem  Option /auto: no pause at the end.
rem ==========================================================================
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup.bat first.
    if /i not "%~1"=="/auto" pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pytest
set "EXITCODE=%ERRORLEVEL%"
if /i not "%~1"=="/auto" pause
exit /b %EXITCODE%
