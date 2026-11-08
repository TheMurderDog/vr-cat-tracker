@echo off
rem Optional, once: installs the Cat Tracker app (a window, a tab in the SteamVR dashboard and a wrist widget) into the
rem same .venv as the tracker, a few hundred MB. You can run it again. To remove it: pip uninstall PySide6-Essentials
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
if exist "%TOP%\my_data\accepted_disclaimer.txt" goto accepted
echo.
echo This is a hobby project, NOT a safety device. It can miss your pet or warn too late.
echo You use it at your own risk, with no warranty. Read 0_start_here\DISCLAIMER.md and LICENSE first.
echo.
set "OK="
set /p "OK=Type YES and press Enter to accept and install: "
if /i not "%OK%"=="YES" (
  echo Not accepted, so nothing was installed.
  pause
  exit /b 1
)
>"%TOP%\my_data\accepted_disclaimer.txt" echo Disclaimer and license accepted on %DATE% %TIME%
:accepted
cd /d "%TOP%"
.venv\Scripts\python.exe -m pip install -r engine\requirements-app.txt
if not "%errorlevel%"=="0" goto fail
echo.
echo The app is installed.
echo From now on it opens by itself whenever the tracker starts (run_tracker.bat, the VRChat launchers,
echo the restart scripts and the SteamVR autostart). To open it on its own: 2_open_app.bat.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
