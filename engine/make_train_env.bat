@echo off
rem Creates the training environment, .venv-train in the top folder, if it is not there yet. Used by
rem 3_first_test\1_get_stock_model.bat and 4_teach_it_your_cat\3_train.bat. It installs PyTorch with CUDA and
rem Ultralytics (about 3.5 GB, one time), separate from the main .venv so the two never clash.
set "TOP=%~dp0.."
set "TPY=%TOP%\.venv-train\Scripts\python.exe"
if exist "%TPY%" exit /b 0
py -3.12 --version >nul 2>&1 || (
  echo Python 3.12 was not found. Run 0_start_here\1_install.bat first.
  exit /b 1
)
echo Creating the training environment in .venv-train, one time only. It downloads about 3.5 GB ...
py -3.12 -m venv "%TOP%\.venv-train" || goto fail
"%TPY%" -m pip install --upgrade pip || goto fail
"%TPY%" -m pip install torch==2.14.1+cu130 torchvision==0.29.1+cu130 --index-url https://download.pytorch.org/whl/cu130 || goto fail
"%TPY%" -m pip install -r "%TOP%\engine\cat_tracker\requirements-train.txt" || goto fail
exit /b 0
:fail
echo Setting up the training environment FAILED. Delete the .venv-train folder and try again.
exit /b 1
