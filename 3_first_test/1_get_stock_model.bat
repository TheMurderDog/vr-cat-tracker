@echo off
rem Gets the stock YOLO11s model (trained on everyday photos, which include cats) and exports it for the tracker,
rem into my_data\models. The first run also creates the training environment (about 3.5 GB, one time).
set "TOP=%~dp0.."
if exist "%TOP%\my_data\models\yolo11s.onnx" (
  echo The stock model is already there: my_data\models\yolo11s.onnx
  goto next
)
call "%TOP%\engine\make_train_env.bat" || goto fail
if not exist "%TOP%\my_data\models" mkdir "%TOP%\my_data\models"
cd /d "%TOP%\my_data\models"
echo Downloading yolo11s.pt from Ultralytics and exporting it ...
"%TOP%\.venv-train\Scripts\python.exe" "%TOP%\engine\tools\get_stock_model.py" || goto fail
if not exist yolo11s.onnx goto fail
echo Saved my_data\models\yolo11s.onnx
:next
echo.
echo Next: run 2_desktop_test.bat with your cat in the room.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Getting the stock model FAILED. The details are above. Press any key to close.
pause >nul
exit /b 1
