@echo off
rem Adds new capture sessions quickly: starts from the last trained model and trains 20 epochs on every checked
rem session (old and new together, so it does not forget the old ones). Run 3_train.bat once first.
set "TOP=%~dp0..\.."
call "%TOP%\4_teach_it_your_cat\3_train.bat" --resume-from-last %*
