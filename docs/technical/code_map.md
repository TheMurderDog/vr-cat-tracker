# Code map

All code is in `engine`. Step scripts change into `engine` and run `python -m <module>`, so imports are
package-absolute (`from core.config import ...`). Modules with an entry point have a `main()`.

## Step scripts and what they run

| Script | Runs | Python |
| --- | --- | --- |
| `0_start_here\1_install.bat` | `pip install -r engine\requirements.txt` and `requirements-pose.txt`, then `rtmlib==0.0.16 --no-deps` | creates `.venv` |
| `1_connect_cameras\1_set_up_cameras.bat` | `tools.camera_setup` | `.venv` |
| `1_connect_cameras\troubleshoot_find_cameras.bat` | `tools.probe_cameras` | `.venv` |
| `1_connect_cameras\troubleshoot_preview_cameras.bat` | `tools.preview` | `.venv` |
| `2_calibrate_cameras\1_lens_calibration.bat` | `tools.calib_intrinsics --cam <name>` | `.venv` |
| `2_calibrate_cameras\2_room_calibration.bat` | `tools.calib_room` | `.venv` |
| `2_calibrate_cameras\3_check_calibration.bat` | `tools.calib_check` | `.venv` |
| `3_first_test\1_get_stock_model.bat` | `engine\make_train_env.bat`, then `yolo export model=yolo11s.pt ...` in `my_data\models` | `.venv-train` |
| `3_first_test\2_desktop_test.bat` | `cat_tracker.run --no-vr` | `.venv` |
| `4_teach_it_your_cat\1_capture.bat` | `cat_tracker.run --no-vr --capture` | `.venv` |
| `4_teach_it_your_cat\2_label.bat` | `cat_tracker.label` (runs `cat_tracker.autolabel` on a new session first) | `.venv` |
| `4_teach_it_your_cat\3_train.bat` | `engine\make_train_env.bat`, then `cat_tracker.train` | `.venv-train` |
| `4_teach_it_your_cat\later_rounds\train_more.bat` | `3_train.bat --resume-from-last` | `.venv-train` |
| `4_teach_it_your_cat\later_rounds\train_big.bat` | `3_train.bat --epochs 100 --patience 30` | `.venv-train` |
| `4_teach_it_your_cat\later_rounds\check_recording.bat` | `cat_tracker.check_recording` | `.venv` |
| `5_play_in_vr\run_tracker.bat` | `cat_tracker.run` | `.venv` |
| `5_play_in_vr\stop_tracker.bat` | writes `my_data\tracker\stop` | none |
| `5_play_in_vr\restart_tracker.bat` | stop file, then `pythonw engine\cat_tracker\autostart.py --reuse-anchor --headless` | `.venv` |
| `5_play_in_vr\start_with_steamvr\install_autostart.bat` | `cat_tracker.install_autostart` | `.venv` |
| `5_play_in_vr\start_with_steamvr\remove_autostart.bat` | `cat_tracker.install_autostart --remove` | `.venv` |
| `5_play_in_vr\app\1_install_app.bat` | `pip install -r engine\requirements-app.txt` (PySide6) | `.venv` |
| `5_play_in_vr\app\2_open_app.bat` | `cat_app.main` | `.venv` |
| `6_optional_vrchat\2_osc_test.bat` | `cat_tracker.osc_test` | `.venv` |
| `6_optional_vrchat\3_run_with_vrchat.bat` | `cat_tracker.run --osc --reuse-anchor` | `.venv` |
| `6_optional_vrchat\4_install_autostart_vrchat.bat` | `cat_tracker.install_autostart --osc` | `.venv` |
| `6_optional_vrchat\restart_with_vrchat.bat` | like `restart_tracker.bat`, plus `--osc` | `.venv` |
| `7_if_something_moved\drift_check.bat` | `tools.drift_check` | `.venv` |

Every script passes its own arguments through (`%*`), so `run_tracker.bat --new-anchor` works. `--reuse-anchor`,
still passed by the restart scripts, autostart and `3_run_with_vrchat.bat`, is accepted and does nothing: the
saved anchor is always used now.

## Modules

### Camera code (from fbt, the full-body tracking project)

| Module | What it does |
| --- | --- |
| `core.config` | loads `settings/cameras.yaml`; `REPO_ROOT` (the top folder), `ENGINE`, `DATA`, `get(cfg, "a.b")`, `resolve_path()` |
| `capture.devices` | Windows' camera list in DirectShow order (name and device path per OpenCV id), with ctypes only; `looks_like_headset` |
| `core.runlog` | a timestamped log file per run, with the command line, versions and full config in its header; prunes old logs |
| `capture.camera` | one capture thread per camera: fixed mode, locked settings, arrival timestamps, live stats; `open_cameras`, `camera_names`, `rotations`, `resolve_ids` (finds each camera by its saved USB device, skips `cameras.exclude`), `excluded`, and `label_tile` / `tile_grid`, the layout every multi-camera window uses |
| `calibration.board` | ChArUco boards from the settings, and a small PDF writer so they print at exact size |
| `calibration.intrinsics` | lens calibration from board views (fisheye and rational models, outlier rejection), `project()` |
| `calibration.room` | places every camera in SteamVR space from a tracker carrying a printed marker |
| `core.single` | `hold_cameras()`: one camera tool at a time (waits with a plain message); the lock ends with the process |
| `calibration.room_needs` | after a room solve: which cameras are GOOD and, for the others, what they need in plain words (stops, coverage of the view, depth and height range, tilt); `try_solve` never raises (pure logic) |
| `calibration.wave` | picks Board B's device by waving: the tracker or controller that moved the most, by a clear margin (pure logic) |
| `calibration.vr` | reads tracker poses from SteamVR on a background thread, on the same clock as the camera frames |
| `calibration.drift` | compares a fresh frame with the reference saved at room calibration |
| `fusion.triangulate` | confidence-weighted multi-camera triangulation with outlier rejection; `Rig` |
| `fusion.filters` | `OneEuro` filter and `JumpGate` |
| `fusion.align` | keeps the cameras' idea of SteamVR space lined up with SteamVR; `head_point` |
| `pose.baseline` | RTMPose (Halpe 26 keypoints) via rtmlib on ONNX Runtime; `PoseModels`, `CameraPose`, `prepare_onnxruntime` |
| `tools.camera_setup` | entry: the camera setup screen; shows each used camera's fps, drops, flicker and brightness (`CameraStats`, as `tools.preview` does); writes `cameras.ids`, `names`, `rotate`, `devices`, `exclude` (and `backend` if it had to switch driver) with `save_settings`, after a backup |
| `tools.probe_cameras` | entry: which camera ids open, and which give the configured mode (troubleshooting) |
| `tools.preview` | entry (troubleshooting): live view of every camera, exposure steps, and a soak test (`--seconds`) |
| `tools.refit_lenses` | no launcher: solves the lens calibrations again from their saved pictures with the printer-stretch check (per camera and all together), and the room from its saved stops, into `my_data/calibration/stretch_corrected`; backs up first, applies nothing |
| `tools.make_boards` | entry: the printable board and marker PDFs, for custom sizes only (no launcher: [custom_boards.md](custom_boards.md)) |
| `tools.calib_intrinsics` | entry: the lens calibration wizard: every camera in turn (or `--cam`), fullscreen, with the next area lit up, an arrow and spoken directions (`direction`, `next_target`); the capture rule and maths are unchanged |
| `tools.voice` | spoken prompts: Piper with the `en_US-ljspeech-medium` voice, each prompt rendered once to `my_data/voice_cache` and played with winsound; falls back to Windows' System.Speech (one PowerShell process, text on stdin), then beeps only. Rate-limited, never blocking the camera loop |
| `tools.get_voice` | entry (from `1_install.bat`): downloads the voice to `engine/voices`, pinned URL, SHA-256 checked |
| `tools.calib_room` | entry: room calibration, fullscreen with big prompts and voice (`--quiet`, `--resolve`, `--practice`): wave to pick the device, chime per stop, result screen, backups; also `load_intrinsics(data_dir, names)` |
| `tools.calib_check` | entry: SteamVR's position of Board B against what each camera sees, fullscreen with voice (`--quiet`, `--seconds`); GOOD / OFF per camera and a spoken summary |
| `tools.drift_check` | entry: reports cameras that moved since room calibration |

### Cat tracker

| Module | What it does |
| --- | --- |
| `cat_tracker.run` | entry: the tracker (cameras, detect, locate, anchor, overlays, alerts, capture, hard frames, OSC) |
| `cat_tracker.settings` | loads both settings files into one config (`cfg["cat"]` holds the tracker's); `cameras.fps`: `full` (default) keeps settings/cameras.yaml's speed, the experimental `auto` asks for `AUTO_FPS` (with `Camera.open` falling back if those frames misbehave), a forced number is raised to `MIN_FPS` if lower |
| `cat_tracker.detector` | YOLO11 on ONNX Runtime, every camera in one GPU batch |
| `cat_tracker.locate` | boxes to one 3D point: triangulation or floor projection, room and height checks, weak-box matching |
| `cat_tracker.anchor` | the fit from calibration space to SteamVR raw space, its save file (with the base station map id) and `AnchorCheck`, which corrects it quietly while you play |
| `cat_tracker.vrlink` | SteamVR side: headset pose, raw-to-standing transform, overlays, haptics through SteamVR Input |
| `cat_tracker.alert` | when to warn (distance, closing speed, napping), and the cat's motion state and heading |
| `cat_tracker.health` | notices stale cameras and failing detection; writes the heartbeat |
| `cat_tracker.watchdog` | entry (started by `run`): the "CAT TRACKER STOPPED" notice if the tracker dies or freezes |
| `cat_tracker.notice` | draws text notices as PNG files for overlays |
| `cat_tracker.osc` | the VRChat OSC sender (OSC 1.0 over UDP, written here, no extra package) |
| `cat_tracker.osc_test` | entry: a pretend cat 1 m or 2 m ahead, for lining up the avatar prop |
| `cat_tracker.collect` | `FrameSaver`: training frames with the current model's boxes as first-guess labels |
| `cat_tracker.hardframes` | `HardSaver`: saves the moments the detector struggled with |
| `cat_tracker.autolabel` | entry: fills in missed boxes from other cameras and nearby moments |
| `cat_tracker.label` | entry: the box checking tool |
| `cat_tracker.train` | entry (in `.venv-train`): fine-tunes YOLO11s, exports ONNX, switches `settings/cat_tracker.yaml` |
| `cat_tracker.half` | makes the half-precision copy of a trained model the tracker runs |
| `cat_tracker.check_recording` | entry: runs the detector over a photo or an fbt recording |
| `cat_tracker.install_autostart` | entry: registers or removes the SteamVR startup entry (`cat_tracker.vrmanifest`) |
| `cat_tracker.autostart` | what SteamVR runs: changes into `engine` and runs `cat_tracker.run` with no window (or `cat_app.bridge` with `--via-app`) |

### The app (optional, `engine/cat_app/`, needs PySide6)

| Module | What it does |
| --- | --- |
| `cat_app.main` | entry: the app window (QML), one copy at a time (a second copy shows the first one's window); `--background` (started by SteamVR: no window until asked, quits with SteamVR), `--demo`, `--no-vr` |
| `cat_app.autostart` | what SteamVR runs for the app: `cat_app.main --background` |
| `cat_app.backend` | what the QML sees: tracker status, buttons, settings, the camera picture and heatmap; starts the tracker through `cat_app.bridge` |
| `cat_app.link` | the app-tracker link: named shared memory blocks (status, frame, heatmap, requests), standard library only, no network |
| `cat_app.bridge` | entry: runs the unchanged `cat_tracker.run` in the same process with hooks (window picture, keys, alerts, marker look, heatmap) and serves it over `cat_app.link` |
| `cat_app.vr_dashboard` | the SteamVR dashboard tab: draws the QML offscreen and hands it to SteamVR, laser-pointer input |
| `cat_app.wrist` | the wrist widget overlay and its SteamVR Input actions (`input/*.json`) |
| `cat_app.d3d11_texture` | puts a picture on SteamVR's GPU as a D3D11 texture (Windows, ctypes) |
| `cat_app.app_settings` | the app's own settings (`my_data/app/app_settings.json`): alert tuning, snooze length, wrist widget |
| `cat_app.marker_style` | the marker look (colour, shade, size, opacity) and the recoloured icons |
| `cat_app.extras` | heatmap, rising buzz steps, snooze and capture helpers (pure logic) |
| `cat_app.perf` | CPU and frame-time numbers for `my_data/logs/cat_app/perf.log` |

Data files in the package: `assets/*.png` (overlay images) and `input/*.json` (SteamVR Input actions and controller
bindings for the buzz).

The stable API for building your own package on the camera code is in [camera_core.md](camera_core.md).
