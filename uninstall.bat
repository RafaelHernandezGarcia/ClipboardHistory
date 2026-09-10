@echo off
title ClipboardHistory - uninstall
set "INSTALL_DIR=%LOCALAPPDATA%\ClipboardHistory"
set "START_MENU_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo This removes ClipboardHistory from %INSTALL_DIR%
echo and its Start Menu / Startup shortcuts. The saved history
echo (%LOCALAPPDATA%\ClipboardHistory\history.json) is removed too.
echo.
echo If the app is running, quit it first from its tray icon.
echo.
set /p CONFIRM="Type Y to continue: "
if /i not "%CONFIRM%"=="Y" exit /b 0

del /q "%START_MENU_DIR%\ClipboardHistory.lnk" 2>nul
del /q "%STARTUP_DIR%\ClipboardHistory.lnk" 2>nul
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
echo Done.
pause
