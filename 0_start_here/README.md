# 0. Start here

**First, read [DISCLAIMER.md](DISCLAIMER.md).** This is a hobby project, not a safety device.

Then go through the numbered folders in order. Each has a README like this one, and its scripts are numbered in the
order you run them. Double-click a `.bat` file to run it; each one tells you what to do next.

## Before you start

Get these ready first:

- [ ] **2 or more USB webcams**, mounted high and fixed in place, so every spot your cat walks is seen by at least
      two. More cameras give better results: if tracking is poor later, add one.
      Fixed focus, a manual focus ring, or autofocus that can be switched off. Autofocus that can't be switched off
      will cause tracking problems.
- [ ] **Windows 10 or 11**, an **NVIDIA graphics card**, and **Python 3.12** (python.org, or
      `winget install Python.Python.3.12`).
- [ ] **SteamVR** with your headset, plus a **tracker or a hand controller** you can fix to Board B for step 2 (no
      full-body trackers needed).
- [ ] **Board A and Board B from [print_these](print_these/README.md), printed and mounted** (about 5 minutes, plus
      something rigid like foam board and some stiff card).
- [ ] **About 6 GB of free disk space.**
- [ ] **Good, steady light in the room.** Dim light makes everything slower, labelling most of all (step 4).
- [ ] **Your cat at home** for steps 3 and 4 (about 20 minutes of it wandering and napping in the room).

## Run this

`1_install.bat` - installs everything the tracker needs (about 2 GB of downloads). Safe to run again.

## You're done when

It prints **Setup done**.

## Next

Open [1_connect_cameras](../1_connect_cameras/README.md).

## The other folders

| Folder | What it is |
| --- | --- |
| `6_optional_vrchat` | optional: show your cat to friends in VRChat |
| `7_if_something_moved` | come back here if a camera got bumped or the base stations moved |
| `settings` | the two settings files |
| `my_data` | everything made on your PC (calibration, captures, models, logs) |
| `docs` | how it works, and details for developers |
| `engine` | the code. You never need to open it. |

## Your notes

<!-- I think we should change the readme to something more legible like a clean text file or even a PDF. Try to format it in a way that is easy for a human eye to follow. This is a bit cluttered and verbose. Remember this is for the human trying to set this up without help. We are the help. Leave the disclaimers to the disclaimer doc. Keep the readme strictly for instructions. Just tell the user to read the disclaimer first before continuing. Also let the user know that they may need to ad more cameras if they do not get good results. Also apply this to all readme files in all steps. Thank you. -->
