@echo off
rem Lens calibration for one camera. Asks which camera unless given, e.g. calib_intrinsics.bat cam1
cd /d "%~dp0"
set CAM=%1
if "%CAM%"=="" set /p CAM=Which camera (a name from cameras.names in config.yaml, or its number)? 
.venv\Scripts\python.exe -m tools.calib_intrinsics --cam %CAM% %2 %3
pause
