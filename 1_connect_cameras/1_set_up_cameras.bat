@echo off
rem The camera setup screen: shows every connected camera live. Pick the ones to use, name them, put them in order
rem and turn them upright, then press s to save them to settings\cameras.yaml.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.camera_setup %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: open 2_calibrate_cameras and read its README.md.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
