@echo off
rem Troubleshooting: live view of every camera with fps, dropped frames and brightness. --seconds 600 runs a soak test.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.preview %*
if not "%errorlevel%"=="0" goto fail
echo.
echo [ and ] try shorter and longer exposures; put the value it logs in settings\cameras.yaml as exposure_ms.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
