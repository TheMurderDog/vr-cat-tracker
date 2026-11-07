@echo off
rem An overnight training run: up to 300 epochs, stops by itself when it stops improving, at most 6 hours. Keeps the
rem PC from sleeping (the screen may still turn off). If it gets interrupted (a restart, a power cut), run this again
rem and it picks up where it stopped. In the morning: a summary here and in my_data\training\summary_*.txt.
rem The new model is only used if it finds the cat better than the one you have.
rem It asks once whether to shut the PC down when it's done. Then, whether training worked or not, the summary and
rem logs are written first, and Windows shuts down 2 minutes later ("shutdown /a" in a command window stops it).
rem Never in the middle of a run. CAT_SHUTDOWN_DRY=1 prints the shutdown command instead of running it (a test).
setlocal
set "TOP=%~dp0..\.."
set "OFF=N"
if /i "%CAT_SHUTDOWN_ANSWER%"=="N" goto start
if /i "%CAT_SHUTDOWN_ANSWER%"=="Y" goto yes
choice /c YN /n /m "Shut down the PC when training finishes? (y/N) "
if errorlevel 2 goto start
:yes
set "OFF=Y"
set "CAT_UNATTENDED=1"
:start
if "%OFF%"=="Y" (echo The PC will shut down 2 minutes after training finishes.) else (echo The PC stays on afterwards.)
call "%TOP%\4_teach_it_your_cat\3_train.bat" --overnight %*
set "RESULT=%errorlevel%"
if not "%OFF%"=="Y" exit /b %RESULT%
echo.
if not "%RESULT%"=="0" echo Training did not finish: the details are above and in my_data\logs.
echo Shutting down in 2 minutes. To cancel: open a command window and type shutdown /a
if "%CAT_SHUTDOWN_DRY%"=="1" (
  echo [test] would run: "%SystemRoot%\System32\shutdown.exe" /s /t 120
  exit /b %RESULT%
)
"%SystemRoot%\System32\shutdown.exe" /s /t 120 /c "Cat tracker training has finished. Shutting down in 2 minutes. To cancel: shutdown /a"
exit /b %RESULT%
