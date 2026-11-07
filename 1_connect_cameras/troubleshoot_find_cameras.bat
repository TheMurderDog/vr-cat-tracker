@echo off
rem Troubleshooting, if the setup screen can't see a camera: lists which camera ids open and which give the mode in settings\cameras.yaml (cameras.width/height/fourcc/fps).
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.probe_cameras %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: run 1_set_up_cameras.bat. If a camera is missing there, check the cable and that no other
echo program is using it. Add --backend msmf or --backend dshow here to try the other camera driver.
echo.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
