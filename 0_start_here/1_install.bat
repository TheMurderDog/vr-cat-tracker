@echo off
rem One-time install: creates the Python environment in .venv (in the top folder) and installs the camera code and
rem the pose model the anchor uses. Needs Python 3.12. Safe to run again: it only installs what is missing.
set "TOP=%~dp0.."
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
if not exist "%TOP%\my_data" mkdir "%TOP%\my_data"
>"%TOP%\my_data\accepted_disclaimer.txt" echo Disclaimer and license accepted on %DATE% %TIME%
:accepted
py -3.12 --version >nul 2>&1 || (
  echo Python 3.12 was not found. Install it from python.org, or run: winget install Python.Python.3.12
  echo Then run this again.
  pause
  exit /b 1
)
cd /d "%TOP%"
if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment in .venv ...
  py -3.12 -m venv .venv || goto fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip || goto fail
.venv\Scripts\python.exe -m pip install -r engine\requirements.txt || goto fail
.venv\Scripts\python.exe -m pip install -r engine\requirements-pose.txt || goto fail
.venv\Scripts\python.exe -m pip install --no-deps rtmlib==0.0.16 || goto fail
rem the calibration wizards' voice: Piper (offline speech) and its one voice, checked against its SHA-256.
rem --no-deps, as Piper would add CPU onnxruntime over the GPU one already installed.
.venv\Scripts\python.exe -m pip install --no-deps piper-tts==1.8.0 pathvalidate==3.3.1 || goto fail
cd engine
..\.venv\Scripts\python.exe -m tools.get_voice
rem the pose model the anchor walk (step 5) uses, from OpenMMLab: fetched now, not in the middle of the walk
..\.venv\Scripts\python.exe -m pose.get_models
cd ..
echo.
echo Setup done.
echo Next: plug in and mount your cameras, then open 1_connect_cameras and read its README.md.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Install FAILED. Read the error above. Deleting the .venv folder and running this again often fixes it.
echo Press any key to close.
pause >nul
exit /b 1
