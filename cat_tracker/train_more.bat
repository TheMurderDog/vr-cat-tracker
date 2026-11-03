@echo off
rem Adds new capture sessions quickly: starts from the last fine-tuned model and trains 20 epochs on
rem every checked session (old and new together, so it does not forget the old ones). Run train.bat once first.
call "%~dp0train.bat" --resume-from-last %*
