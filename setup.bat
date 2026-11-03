@echo off
rem One-time setup: creates .venv (Python 3.12) and installs requirements.txt.
rem "setup.bat pose" also installs the optional pose model (requirements-pose.txt).
cd /d "%~dp0"
py -3.12 --version >nul 2>&1 || (echo Python 3.12 not found. Install it, e.g.: winget install Python.Python.3.12 & pause & exit /b 1)
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || (echo Install FAILED & pause & exit /b 1)
if /i "%1"=="pose" (
  .venv\Scripts\python.exe -m pip install -r requirements-pose.txt || (echo Pose install FAILED & pause & exit /b 1)
  .venv\Scripts\python.exe -m pip install --no-deps rtmlib==0.0.16 || (echo Pose install FAILED & pause & exit /b 1)
)
echo Setup done. Next: probe_cameras.bat
pause
