@echo off
rem The tracker plus VRChat: sends its position to your avatar over OSC (turn OSC on in VRChat:
rem Action Menu > Options > OSC). Reuses the saved anchor, so no walk-around. Start SteamVR first.
call "%~dp0run.bat" --osc --reuse-anchor %*
