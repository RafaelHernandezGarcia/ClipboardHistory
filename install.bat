@echo off
setlocal enabledelayedexpansion
title ClipboardHistory - Windows installer
:: "install.bat /quiet" = no pauses (for scripted installs)
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"
echo ============================================================
echo   ClipboardHistory - Windows installation
echo ============================================================
echo.
echo   Installs a private copy of the app with its own Python
echo   virtual environment (no system-wide packages touched):
echo.
echo     %LOCALAPPDATA%\ClipboardHistory
echo.
echo   Adds a Start Menu entry and starts the app at login.
echo   Windows already has Win+V, so this app uses Ctrl+Shift+V
echo   (change it from the tray menu).
echo.

:: ------------------------------------------------------------------
:: 1. Folders
:: ------------------------------------------------------------------
set "SCRIPT_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\ClipboardHistory"
set "START_MENU_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: ------------------------------------------------------------------
:: 2. Find a Python 3.10+ interpreter (Windows Store stubs are skipped)
:: ------------------------------------------------------------------
set "PYTHON_EXE="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%PROGRAMFILES%\Python312\python.exe"
    "%PROGRAMFILES%\Python313\python.exe"
    "%PROGRAMFILES%\Python311\python.exe"
    "%PROGRAMFILES%\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python313\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if not defined PYTHON_EXE if exist %%P set "PYTHON_EXE=%%~P"
)
if not defined PYTHON_EXE (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYTHON_EXE (
            echo %%P | findstr /i "WindowsApps" >nul || set "PYTHON_EXE=%%P"
        )
    )
)
if not defined PYTHON_EXE (
    echo ERROR: Python 3.10+ not found. Install it from python.org and re-run.
    pause
    exit /b 1
)
echo Using Python : %PYTHON_EXE%
echo Installing to: %INSTALL_DIR%
echo.

:: ------------------------------------------------------------------
:: 3. Ask a running copy to quit cleanly (over its single-instance port)
:: ------------------------------------------------------------------
"%PYTHON_EXE%" "%SCRIPT_DIR%main.py" --quit >nul 2>&1
if not errorlevel 1 (
    echo Asked the running copy of ClipboardHistory to quit...
    ping -n 4 127.0.0.1 >nul
)
:check_running
"%PYTHON_EXE%" -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',47410)) else 1)" >nul 2>&1
if not errorlevel 1 (
    if defined QUIET (
        echo Waiting for the running copy to exit...
        ping -n 3 127.0.0.1 >nul
        goto :check_running
    )
    echo.
    echo A copy of ClipboardHistory is still running. Right-click its tray icon,
    echo choose Quit ClipboardHistory, then press any key to continue.
    pause >nul
    goto :check_running
)

:: ------------------------------------------------------------------
:: 4. Copy the app files (an existing config.json is never overwritten)
:: ------------------------------------------------------------------
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\assets" mkdir "%INSTALL_DIR%\assets"
copy /Y "%SCRIPT_DIR%*.py" "%INSTALL_DIR%\" >nul
copy /Y "%SCRIPT_DIR%requirements.txt" "%INSTALL_DIR%\" >nul
copy /Y "%SCRIPT_DIR%config.example.json" "%INSTALL_DIR%\" >nul
if exist "%SCRIPT_DIR%assets\*" copy /Y "%SCRIPT_DIR%assets\*" "%INSTALL_DIR%\assets\" >nul

:: ------------------------------------------------------------------
:: 5. Private virtual environment + dependencies
:: ------------------------------------------------------------------
if not exist "%INSTALL_DIR%\.venv\Scripts\python.exe" (
    echo Creating virtual environment...
    "%PYTHON_EXE%" -m venv "%INSTALL_DIR%\.venv"
    if errorlevel 1 (
        echo ERROR: could not create the virtual environment.
        pause
        exit /b 1
    )
)
echo Installing dependencies (first time takes about a minute)...
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install -r "%INSTALL_DIR%\requirements.txt" --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Check your network / proxy and re-run.
    pause
    exit /b 1
)

set "PYTHONW_EXE=%INSTALL_DIR%\.venv\Scripts\pythonw.exe"

:: ------------------------------------------------------------------
:: 6. Shortcuts: Start Menu (searchable) + Startup (auto-start at login)
:: ------------------------------------------------------------------
echo Creating shortcuts...
set "VBS_FILE=%TEMP%\ch_make_shortcuts.vbs"
> "%VBS_FILE%" echo Set oWS = WScript.CreateObject("WScript.Shell")
>> "%VBS_FILE%" echo Set oLink = oWS.CreateShortcut("%START_MENU_DIR%\ClipboardHistory.lnk")
>> "%VBS_FILE%" echo oLink.TargetPath = "%PYTHONW_EXE%"
>> "%VBS_FILE%" echo oLink.Arguments = """%INSTALL_DIR%\main.py"""
>> "%VBS_FILE%" echo oLink.WorkingDirectory = "%INSTALL_DIR%"
>> "%VBS_FILE%" echo oLink.Description = "ClipboardHistory - clipboard history (Ctrl+Shift+V)"
>> "%VBS_FILE%" echo oLink.IconLocation = "%INSTALL_DIR%\assets\icon.ico"
>> "%VBS_FILE%" echo oLink.Save
>> "%VBS_FILE%" echo Set oLink = oWS.CreateShortcut("%STARTUP_DIR%\ClipboardHistory.lnk")
>> "%VBS_FILE%" echo oLink.TargetPath = "%PYTHONW_EXE%"
>> "%VBS_FILE%" echo oLink.Arguments = """%INSTALL_DIR%\main.py"""
>> "%VBS_FILE%" echo oLink.WorkingDirectory = "%INSTALL_DIR%"
>> "%VBS_FILE%" echo oLink.Description = "ClipboardHistory - auto start"
>> "%VBS_FILE%" echo oLink.IconLocation = "%INSTALL_DIR%\assets\icon.ico"
>> "%VBS_FILE%" echo oLink.Save
cscript //nologo "%VBS_FILE%"
del "%VBS_FILE%"

:: ------------------------------------------------------------------
:: 7. Launch it now
:: ------------------------------------------------------------------
echo.
echo ============================================================
echo   Installed.
echo ============================================================
echo   - Press Ctrl+Shift+V to open the clipboard history.
echo   - It starts automatically at login (tray menu can turn that off).
echo   - Change the shortcut from the tray menu.
echo.
start "" /D "%INSTALL_DIR%" "%PYTHONW_EXE%" "%INSTALL_DIR%\main.py"
if not defined QUIET pause
