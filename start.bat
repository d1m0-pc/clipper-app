@echo off
rem ==========================================================================
rem  Clipper - start the application (double-click this file)
rem ==========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto :install
".venv\Scripts\python.exe" -c "import tkinter, yt_dlp" >nul 2>nul
if errorlevel 1 goto :install
goto :run

:install
echo The application is not installed yet, or some packages are missing.
echo Running setup.bat ...
echo.
call "%~dp0setup.bat"
if errorlevel 1 (
    echo.
    echo Installation failed. See the messages above.
    pause
    exit /b 1
)

:run
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0
