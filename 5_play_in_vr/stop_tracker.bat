@echo off
rem Closes the cat tracker when it runs with no window (started with SteamVR). It stops within a second or two.
rem Closing SteamVR closes it too.
set "TOP=%~dp0.."
if not exist "%TOP%\my_data\tracker" mkdir "%TOP%\my_data\tracker"
echo stop> "%TOP%\my_data\tracker\stop"
echo Asked the cat tracker to stop.
timeout /t 2 >nul
