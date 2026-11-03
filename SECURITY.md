# Security

## Reporting a problem

Please report security problems privately, through GitHub's **Report a vulnerability** button on this repository's
Security tab, rather than in a public issue.

## What this software does and doesn't do

- It runs locally on your PC. It **opens no network ports** and accepts no network input.
- The only thing it sends is the VRChat OSC output (`run.bat --osc`): UDP packets with the cat's position and your
  head's position in the room, sent to `127.0.0.1:9000` (this PC) by default. Changing `vrchat.host` in
  `cat_tracker/config.yaml` would send that data to another machine, unencrypted.
- It downloads files only when you set it up or train: Python packages (pip, from PyPI and the PyTorch index, with
  pinned versions for the core), the YOLO11 weights (from Ultralytics, by `yolo export`/`train.bat`) and the optional
  pose models (from OpenMMLab, by rtmlib).

## Things to be careful with

- **Model files can contain code.** `.pt` files are Python pickles, and loading one can run code. Only use
  `train.bat --base` and `yolo export` with `.pt` files from sources you trust. ONNX files (`.onnx`) are data.
- **It saves pictures by itself.** Besides `capture.bat`, the tracker saves "hard" frames for training while it runs
  (up to 150 moments per run; turn off with `hard_frames.enabled: false`). Anyone in view of the cameras can end up
  in them.
- **Your captures are pictures of your room.** `cat_tracker/captures`, `cat_tracker/logs` (snapshots) and
  `calibration/data` (reference pictures from each camera) show your room and anyone in it. They are in `.gitignore`;
  think twice before sharing them anywhere.
- **Calibration files are yours.** Calibration results are JSON and plain data, so loading someone else's can't run code,
  but they won't match your cameras.
- **Autostart** (`install_autostart.bat`) registers the tracker with SteamVR using the absolute path of this folder's
  Python. Anyone who can write to this folder can change what runs when SteamVR starts, the same as with any program.
