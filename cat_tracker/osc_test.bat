@echo off
rem Test mode for lining up the avatar: a pretend cat held 1 m ahead of you (keys 1 / 2 = 1 m / 2 m, q = quit).
rem Start SteamVR and VRChat (OSC on) first, and close the real tracker so they do not both send.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.osc_test %*
pause
