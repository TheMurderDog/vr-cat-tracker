@echo off
rem Fine-tunes the cat detector on your labelled captures (run label.bat first).
rem Uses its own environment, cat_tracker\.venv, never the camera core's .venv. The first run creates it and installs
rem PyTorch with CUDA and Ultralytics (about 3.5 GB, one time). Training then takes roughly 20 to 60 minutes.
cd /d "%~dp0.."
set PY=cat_tracker\.venv\Scripts\python.exe
if not exist %PY% (
  echo Creating the training environment in cat_tracker\.venv, one time only ...
  py -3.12 -m venv cat_tracker\.venv || goto fail
  %PY% -m pip install --upgrade pip || goto fail
  %PY% -m pip install torch==2.14.1+cu130 torchvision==0.29.1+cu130 --extra-index-url https://download.pytorch.org/whl/cu130 || goto fail
  %PY% -m pip install -r cat_tracker\requirements-train.txt || goto fail
)
%PY% -m cat_tracker.train %*
goto done
:fail
echo Setup FAILED. Delete the cat_tracker\.venv folder and run train.bat again.
:done
pause
