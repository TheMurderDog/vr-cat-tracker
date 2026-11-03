@echo off
rem Closes the cat tracker when it runs with no window (started with SteamVR). It stops within a second or two.
rem Closing SteamVR closes it too.
cd /d "%~dp0"
if not exist data mkdir data
echo stop> data\stop
echo Asked the cat tracker to stop.
timeout /t 2 >nul
