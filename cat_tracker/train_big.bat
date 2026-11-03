@echo off
rem A big training run: starts fresh from the stock model and trains up to 100 epochs on every checked
rem session (stops early if it stops improving for 30). Takes about an hour; the GPU is busy the whole time.
call "%~dp0train.bat" --epochs 100 --patience 30 %*
