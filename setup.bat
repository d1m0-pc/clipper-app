@echo off
rem ==========================================================================
rem  Clipper - install dependencies (double-click this file)
rem  Creates the virtual environment .venv and installs everything from
rem  requirements.txt, then the latest yt-dlp:  pip install -U --pre "yt-dlp[default]"
rem  Option /auto: no questions and no pause at the end.
rem ==========================================================================
setlocal
cd /d "%~dp0"
title Clipper - setup
set "EXITCODE=0"
set "AUTO="
if /i "%~1"=="/auto" set "AUTO=1"

echo ============================================================
echo   Clipper - setup
echo ============================================================
echo.

rem --- 1. Find Python -------------------------------------------------------
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :no_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :no_python
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do set "PYVER=%%v"
echo Found Python %PYVER%

rem --- 2. Virtual environment -----------------------------------------------
if exist ".venv\Scripts\python.exe" goto :venv_ready
echo Creating the virtual environment in the .venv folder ...
%PY% -m venv .venv
if errorlevel 1 goto :venv_failed
:venv_ready
set "VPY=%~dp0.venv\Scripts\python.exe"

"%VPY%" -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :no_tkinter

rem --- 3. Install packages --------------------------------------------------
echo.
echo [1/3] Updating pip ...
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 echo [!] pip was not updated, continuing with the current version.

echo.
echo [2/3] Installing dependencies from requirements.txt ...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_failed

echo.
echo [3/3] Installing the latest yt-dlp ...
"%VPY%" -m pip install --disable-pip-version-check -U --pre "yt-dlp[default]"
if errorlevel 1 goto :pip_failed

"%VPY%" -c "import yt_dlp, clipper_app.gui.app" >nul 2>nul
if errorlevel 1 goto :import_failed

rem --- 4. External programs: ffmpeg and Deno --------------------------------
echo.
echo Checking external programs:
set "NEED_FFMPEG="
set "NEED_DENO="
where ffmpeg >nul 2>nul
if errorlevel 1 (
    set "NEED_FFMPEG=1"
    echo   [!]  ffmpeg was NOT found - it is needed to cut clips.
    echo        Install command:  winget install Gyan.FFmpeg
) else (
    echo   [OK] ffmpeg was found.
)
where deno >nul 2>nul
if errorlevel 1 (
    set "NEED_DENO=1"
    echo   [!]  Deno was NOT found - yt-dlp uses it for YouTube.
    echo        Install command:  winget install DenoLand.Deno
) else (
    echo   [OK] Deno was found.
)

if defined AUTO goto :done
if defined NEED_FFMPEG call :offer_install "ffmpeg" "Gyan.FFmpeg"
if defined NEED_DENO call :offer_install "Deno" "DenoLand.Deno"
goto :done

rem --------------------------------------------------------------------------
:offer_install
echo.
set "ANSWER="
set /p "ANSWER=Do you want me to install %~1 with winget now? [Y/N]: "
if /i not "%ANSWER%"=="Y" goto :eof
where winget >nul 2>nul
if errorlevel 1 (
    echo [!] winget is not available. Install "App Installer" from the Microsoft Store
    echo     or see README.md for manual installation.
    goto :eof
)
winget install --id %~2 -e --accept-source-agreements --accept-package-agreements
echo If the installation succeeded, CLOSE this window and start the application again.
goto :eof

:done
echo.
echo ============================================================
echo   Setup is complete.
echo   Start the application by double-clicking start.bat
echo ============================================================
goto :end

:no_python
echo [ERROR] Python 3.10 or newer was not found.
echo Install Python 3.14 from https://www.python.org/downloads/
echo and during installation be sure to check "Add python.exe to PATH".
set "EXITCODE=1"
goto :end

:venv_failed
echo [ERROR] The virtual environment .venv could not be created.
echo Check that the folder is not read-only, then try again.
set "EXITCODE=1"
goto :end

:no_tkinter
echo [ERROR] Python is missing tkinter, which the application window needs.
echo Run the Python installer again, choose "Modify" and enable
echo the "tcl/tk and IDLE" option.
set "EXITCODE=1"
goto :end

:pip_failed
echo [ERROR] Package installation failed.
echo Check your internet connection and run setup.bat again.
set "EXITCODE=1"
goto :end

:import_failed
echo [ERROR] The packages were installed, but the application cannot load them.
echo Delete the .venv folder and run setup.bat again.
set "EXITCODE=1"
goto :end

:end
echo.
if not defined AUTO pause
exit /b %EXITCODE%
