@echo off
setlocal EnableExtensions
title SP-404 MK2 Simple Converter - Setup
cd /d "%~dp0"

echo ================================================
echo   SP-404 MK2 Simple Converter
echo   First-run setup + launch
echo ================================================
echo.

rem --- Locate a Python interpreter -------------------------------------
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo [ERROR] Python 3 was not found on this system.
    echo Install it from https://www.python.org/downloads/
    echo and make sure to check "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)
echo Using Python: %PYCMD%
%PYCMD% --version

rem --- Create virtual environment (first time only) ---------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [1/3] Creating virtual environment...
    %PYCMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo.
    echo [1/3] Virtual environment already exists - skipping.
)

rem --- Install / update dependencies ------------------------------------
echo [2/3] Installing dependencies (first time may take a while)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Could not install the dependencies.
    pause
    exit /b 1
)

rem --- Launch the app ----------------------------------------------------
echo [3/3] Launching the app...
echo.
start "" ".venv\Scripts\pythonw.exe" main.py

endlocal