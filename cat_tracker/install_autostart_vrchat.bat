@echo off
rem Same as install_autostart.bat, with VRChat on: the tracker starts with SteamVR and sends it to your avatar.
rem SteamVR must be running. To undo: install_autostart.bat --remove
call "%~dp0install_autostart.bat" --osc %*
