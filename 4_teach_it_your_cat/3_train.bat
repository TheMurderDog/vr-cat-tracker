@echo off
rem Trains the cat detector on your checked images (run 2_label.bat first), then switches settings\cat_tracker.yaml
rem to the new model. Uses the training environment, .venv-train; the first run creates it (about 3.5 GB).
rem Training takes roughly 20 to 60 minutes. Options pass through, e.g. 3_train.bat --batch 4
rem With CAT_UNATTENDED=1 (the overnight run, shutting down after) it never waits for a key press.
set "TOP=%~dp0.."
call "%TOP%\engine\make_train_env.bat" || goto fail
cd /d "%TOP%\engine"
"%TOP%\.venv-train\Scripts\python.exe" -m cat_tracker.train %* || goto fail
if "%CAT_UNATTENDED%"=="1" exit /b 0
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Training did not finish. The details are above.
if "%CAT_UNATTENDED%"=="1" exit /b 1
echo Press any key to close.
pause >nul
exit /b 1
