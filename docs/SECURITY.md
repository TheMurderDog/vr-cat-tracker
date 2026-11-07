# Security

## Reporting a problem

Please report security problems privately, through GitHub's **Report a vulnerability** button on this repository's
Security tab, rather than in a public issue.

## What this software does and doesn't do

- It runs locally on your PC. It **opens no network ports** and accepts no network input.
- The only thing it sends is the VRChat OSC output (`5_play_in_vr\run_tracker.bat --osc`): UDP packets with the cat's position and your
  head's position in the room, sent to `127.0.0.1:9000` (this PC) by default. Changing `vrchat.host` in
  `settings/cat_tracker.yaml` would send that data to another machine, unencrypted.
- It downloads files only when you set it up or train: Python packages (pip, from PyPI and the PyTorch index, with
  pinned versions for the core), the YOLO11 weights (from Ultralytics, by `3_first_test\1_get_stock_model.bat`), the
  pose models (from OpenMMLab, by rtmlib) and the calibration voice (from Hugging Face, a pinned version checked
  against its SHA-256 before it's used, by `0_start_here\1_install.bat`).
- Ultralytics (the training library) normally sends anonymous usage events to Ultralytics while it trains or
  exports, when "sync" is on in your Ultralytics settings (the default). This project switches that off in its own
  processes (`engine/core/ultra.py`), without changing your settings file. Its downloads still work: the YOLO11
  weights, and a small model (`yolo26n.pt`) Ultralytics loads to check mixed precision on the first training run.
  To switch the events off for every program on your PC: `yolo settings sync=False` in the training environment.

## Things to be careful with

- **Model files can contain code.** `.pt` files are Python pickles, and loading one can run code. Only use
  `3_train.bat --base` and `yolo export` with `.pt` files from sources you trust. ONNX files (`.onnx`) are data.
- **It saves pictures by itself.** Besides `4_teach_it_your_cat\1_capture.bat`, the tracker saves "hard" frames for training while it runs
  (up to 150 moments per run; turn off with `hard_frames.enabled: false`). Anyone in view of the cameras can end up
  in them.
- **Your captures are pictures of your room.** `my_data/captures`, `my_data/logs` (snapshots) and
  `my_data/calibration` (reference pictures from each camera) show your room and anyone in it. All of `my_data` is in `.gitignore`;
  think twice before sharing them anywhere.
- **Never attach pictures from `my_data` to a public issue.** Describe the problem in words, or crop a picture so only
  the problem shows. Copying text from a log is fine.
- **Calibration files are yours.** Calibration results are JSON and plain data, so loading someone else's can't run code,
  but they won't match your cameras.
- **Autostart** (`5_play_in_vr\start_with_steamvr\install_autostart.bat`) registers the tracker with SteamVR using the absolute path of this folder's
  Python (`.venv`). It runs as you, never with admin rights. Anyone who can write to this folder can change what runs when SteamVR starts, the same as with any program.
