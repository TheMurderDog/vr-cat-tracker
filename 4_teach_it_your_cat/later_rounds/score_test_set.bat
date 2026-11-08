@echo off
rem Scores the cat model in settings (and the stock model, if it's there) on your test session: how often it finds
rem the cat and how often it sees one that isn't there. Read only. Options pass through, e.g.
rem   score_test_set.bat --model my_data/models/other.onnx
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.score_test_set %*
echo.
echo Press any key to close.
pause >nul
