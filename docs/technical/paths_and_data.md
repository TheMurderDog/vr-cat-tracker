# Paths and data

## Two roots

- **The top folder** (`core.config.REPO_ROOT`) holds the step folders, `settings`, `my_data`, `docs`, `.venv` and
  `.venv-train`. **Every path in a settings file, and every `resolve_path()` call, is relative to it.**
- **`engine`** (`core.config.ENGINE`) holds the code. Python always runs with `engine` as the working folder, so
  `python -m tools.preview` and `from core.config import ...` work.

So a step script does `cd /d "%TOP%\engine"` and runs `"%TOP%\.venv\Scripts\python.exe" -m <module>`, and the code
finds `settings` and `my_data` from `REPO_ROOT`, not from the working folder.

## Python environments

| Folder | Made by | Contains | Used by |
| --- | --- | --- | --- |
| `.venv` | `0_start_here\1_install.bat` | `engine/requirements.txt` (OpenCV, NumPy, SciPy, PyYAML, openvr) and `requirements-pose.txt` (onnxruntime-gpu with CUDA and cuDNN), plus rtmlib with `--no-deps` | every script except training |
| `.venv-train` | `engine\make_train_env.bat` (from `1_get_stock_model.bat` or `3_train.bat`) | PyTorch 2.14.1 and torchvision (CUDA 13), `engine/cat_tracker/requirements-train.txt` (Ultralytics and ONNX tools) | `1_get_stock_model.bat`, `3_train.bat` and `later_rounds` |

The optional app (`5_play_in_vr\app\1_install_app.bat`) adds `engine/requirements-app.txt` (PySide6-Essentials) to `.venv`.

Both are safe to delete; running the script that made them makes them again. Neither is in git.

`engine/voices/` holds the calibration voice (`en_US-ljspeech-medium.onnx` and `.onnx.json`, about 61 MB), downloaded by
`1_install.bat` through `tools.get_voice` and checked against its SHA-256. Not in git; delete it and run `1_install.bat`
again to fetch it again. Piper itself (`piper-tts`, about 45 MB) is in `.venv`.

## settings

| File | Read by | Written by |
| --- | --- | --- |
| `cameras.yaml` | every program (`core.config.load_config`) | you, and `1_set_up_cameras.bat` (`cameras.ids`, `names`, `rotate`, `devices`, `exclude`, sometimes `backend`) after copying it to `my_data/backups` |
| `cat_tracker.yaml` | the cat tracker (`cat_tracker.settings.load`) | you; `3_train.bat` changes `detector.model` and `detector.cat_class` after copying it to `my_data/backups` |

Both are in git: they hold defaults, not secrets. Every key: [settings_reference.md](settings_reference.md).

## my_data

Everything made on the PC. Not in git except `my_data/README.md`.

| Path | Written by | Read by | Safe to delete? |
| --- | --- | --- | --- |
| `calibration/boards/` (`board_small.pdf`, `board_small.png`, `tracker_marker.pdf`) | `python -m tools.make_boards` ([custom_boards.md](custom_boards.md)) | you, to print | yes, makes them again |
| `calibration/intrinsics/<key>/NNN.png` (`<key>`: the camera's `cameras.keys` entry) | `1_lens_calibration.bat` | `1_lens_calibration.bat --from-dir` | yes, but then `--from-dir` can't recalibrate |
| `calibration/intrinsics_<key>.json` | `1_lens_calibration.bat` | everything after step 2 | no: redo lens calibration |
| `calibration/stretch_corrected/` (`intrinsics_<camera>.json`, `room.json`, `refit_report.json`) | `python -m tools.refit_lenses` | you: copy over the live files to use them | yes |
| `calibration/room.json` | `2_room_calibration.bat` | everything after step 2 | no: redo room calibration |
| `calibration/room_device.json` | `2_room_calibration.bat` (the device you waved) | `2_room_calibration.bat`, `3_check_calibration.bat` | yes, you're asked to wave again |
| `calibration/room_recording.json` | `2_room_calibration.bat`, saved as you walk (every couple of seconds) | `2_room_calibration.bat` (offers to continue an unsolved walk with the same cameras and device), `--resolve` | yes, but then an unfinished walk can't be continued |
| `calibration/reference_<key>.png` | `2_room_calibration.bat` | `drift_check.bat` | no: the drift check needs them |
| `models/yolo11s.pt`, `models/yolo11s.onnx` | `1_get_stock_model.bat` | training (`.pt`), the tracker until trained (`.onnx`) | yes, makes them again |
| `models/cat_finetuned.onnx`, `cat_finetuned_half.onnx` | `3_train.bat` | the tracker runs the `_half` one | no: retrain (back up a good one) |
| `captures/<date>-<time>/` | `1_capture.bat` (or `c` in a tracker window) | autolabel, label, train | yes, loses that training data |
| `captures/<date>-<time>-hard/` | the tracker, while it runs | label, train | yes |
| `training/dataset/`, `training/runs/` | `3_train.bat` | `train_more.bat` (`runs`) | `dataset` yes (rebuilt every run); `runs` yes, but `train_more.bat` then needs `3_train.bat` first |
| `backups/cat_tracker_<date>-<time>.yaml` | `3_train.bat` | you | yes |
| `practice/` | `tools.calib_intrinsics --practice`, `tools.calib_room --practice` (`practice/room/`): developer rehearsals | nothing | yes, wiped each practice run |
| `backups/lens_before_refit_<date>-<time>/` | `tools.refit_lenses` | you | yes |
| `backups/room_<date>-<time>/` | `2_room_calibration.bat`, before it overwrites `room.json`, the recording and the reference pictures | you | yes |
| `voice_cache/*.wav` | the calibration wizards (each spoken prompt, rendered once) | the calibration wizards | yes, they're rendered again |
| `backups/cameras_<date>-<time>.yaml` | `1_set_up_cameras.bat` | you | yes |
| `tracker/anchor.json` | the tracker's walk-around, and its quiet corrections while you play | every tracker start, autostart | yes: the next run asks for a walk-around |
| `tracker/heartbeat.json`, `tracker/stop`, `tracker/notice_*.png` | the tracker, `stop_tracker.bat`, the watchdog | the tracker and watchdog | yes, when nothing is running |
| `logs/cameras/` | steps 1, 2 and 7 (`logging` in `cameras.yaml`) | you | yes |
| `logs/cat_tracker/` (incl. `snapshots/`, `watchdog.log`, `autostart_error.txt`) | the tracker and its tools (`logging` in `cat_tracker.yaml`) | you | yes |
| `app/app_settings.json`, `app/marker_style.json` | the app (`5_play_in_vr\app`), when you change an alert or the marker look there | the app and the tracker started through it (`cat_app.bridge`) | yes: back to the defaults |
| `app/running.json` | the app, while it is open (deleted when it closes) | the app at its next start (`cat_app.crash_check`) | yes |
| `app/heatmap.json` | the tracker started through the app, every few seconds | the app's room map | yes: the map starts empty |
| `app/styled/*.png`, `app/snooze.png`, `app/vr_tab/`, `app/wrist.png`, `app/cat_tracker_app.vrmanifest` | the app and `cat_app.bridge` (recoloured icons, the VR tab's and wrist's pictures, a SteamVR Input manifest used when the app isn't registered with SteamVR) | the same | yes, when the app isn't running |
| `logs/cat_app/` (`app.log`, `bridge.log`, `freeze.log`, `perf.log`, `autostart_error.txt`) | the app and `cat_app.bridge` | you | yes |
| `recordings/` | nothing here: `check_recording.bat --session` looks for fbt recordings in it | `check_recording.bat` | n/a |

### A capture session

```
captures/20261104-101500/
  images/<camera>_<n>.jpg     one frame per camera per moment
  labels/<camera>_<n>.txt     YOLO format: "0 cx cy w h", all 0-1; empty file = no cat
  moments.csv                 the time of each moment
  checked.txt                 the stems you passed in 2_label.bat (only these are trained on)
  auto.json                   boxes added by autolabel or the hard-frame saver (shown orange)
```

Calibration JSON formats and coordinate frames: [FORMATS.md](FORMATS.md).

## Outside this folder

- **SteamVR**: `install_autostart.bat` registers `engine/cat_tracker/cat_tracker.vrmanifest` (written next to the
  code, with this PC's paths in it, not in git) as a startup overlay app with the key `camera_core.cat_tracker`.
  `remove_autostart.bat` unregisters it. When the app is installed, the same file also holds a second entry,
  `camera_core.cat_tracker_app` (the app with its dashboard tab), and the tracker entry starts the tracker through
  `cat_app.bridge` so the app can show it. `--no-app` leaves the app out.
- **rtmlib** downloads the pose model to `~/.cache/rtmlib` on first use (URLs under `pose` in `cameras.yaml`).
- **pip** keeps its usual download cache.
