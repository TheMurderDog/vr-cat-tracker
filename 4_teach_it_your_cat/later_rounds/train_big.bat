@echo off
rem A big training run: starts fresh from the stock model and trains up to 100 epochs on every checked session
rem (stops early if it stops improving for 30). Takes about an hour; the GPU is busy the whole time.
set "TOP=%~dp0..\.."
call "%TOP%\4_teach_it_your_cat\3_train.bat" --epochs 100 --patience 30 %*
