# Extending it

## Rules for changes

These keep the folder layout working as the setup guide.

- **Step folders hold only a README and launchers** (`.bat` files, plus files the user handles directly, like the
  Unity package). Code goes in `engine`.
- **Every launcher** sets `TOP` from `%~dp0`, checks `.venv` exists (or says to run `0_start_here\1_install.bat`),
  changes into `engine`, runs `"%TOP%\.venv\Scripts\python.exe" -m <module> %*`, then
  `if not "%errorlevel%"=="0" goto fail`. On success it prints `Next: ...` and closes by itself (`timeout /t 4 >nul`
  for a windowed tool; for a console tool, whose text is the result, "This window closes in 30 seconds" and
  `timeout /t 30 >nul`). `:fail` says "Something went wrong. The details are above. Press any key to close." and
  waits. So a tool returns 0 whenever it ended normally (including a result it showed on screen, good or not), and
  non-zero only when the console text matters.
- **Camera tools take the camera lock** (`core.single.hold_cameras`: `Camera` and the setup screen do it for you), so
  a second one waits with "Another cat tracker tool is still open. Close it and I'll start." The lock is an open
  file handle Windows drops when the process ends, however it ends, so a crash never leaves it stuck. Camera tools
  end with `core.runlog.exit_now(main())`, so the process is gone (and the cameras free) the moment the tool is.
  Copy an existing one. Save them as ASCII with CRLF line endings.
- **Number the scripts in the order they're run.** Scripts you only need sometimes (stop, restart, later rounds) get
  no number.
- **When behaviour changes, update that step's README** in the same change: what, before you start, run in order,
  you're done when, next. User-facing messages in the code name the step script (`run 4_teach_it_your_cat\2_label.bat`),
  not the module.
- **Don't hard-code paths.** Read them from the settings, or use `core.config.resolve_path("my_data/...")`, which
  resolves from the top folder. Code-owned files (assets, input bindings) are referred to as `engine/cat_tracker/...`.
- **Code only writes settings when the user asks it to**, with a backup to `my_data/backups` first, and changing only
  its own keys while keeping every comment: the camera setup screen (`cameras.ids`, `names`, `rotate`, `devices`,
  `exclude`, `backend`,
  via `tools.camera_setup.save_settings`) and training (`detector.model`, `detector.cat_class`).
- **Open cameras through `capture.camera`** (`open_cameras`, or `resolve_ids` then `Camera`), never by a bare id,
  so saved USB devices and `cameras.exclude` are respected.
- **Everything made on the PC goes in `my_data`**, which git ignores. Add a row to
  [paths_and_data.md](paths_and_data.md) and `my_data/README.md` for any new file.
- **Keep it safe by default:** no admin rights, no listening ports, network output only to `127.0.0.1` unless the
  user changes it, pinned package versions, and nothing that runs by itself without an undo script.

## Detecting a different pet

The detector is a YOLO11 ONNX model with a class index:

1. In `settings/cat_tracker.yaml`, set `detector.cat_class` to the COCO class of your pet in the stock model (cat 15,
   dog 16) for a first test.
2. Capture, label and train as in step 4. Training uses a single class, so the trained model's class is 0, and
   `3_train.bat` sets that.
3. Sizes in `locate` and `autolabel` (`body_height_m`, `outline_radius_m`, `radius_m`, `half_height_m`) assume a
   cat. Change them for a bigger or smaller animal.

The names say "cat" throughout; the code doesn't care what the animal is.

## Another output besides SteamVR and VRChat

`cat_tracker.run` has the cat's filtered position in calibration space and, with an anchor, in SteamVR raw and
standing space. `cat_tracker.osc` is the model to copy: a class with its own thread that reads the latest position
and sends it, started only when a flag is given (`--osc`). Add a flag and a settings section for yours, keep it off
by default, and add a launcher and README text in a step folder (an optional step like `6_optional_vrchat`).

## Your own program on the camera code

Put your package in `engine` next to `core`, `capture` and the others, and run it with
`python -m yourpackage.module` from `engine`. Load settings with `core.config.load_config()` (or your own file in
`settings`, as `cat_tracker.settings` does), and resolve paths with `resolve_path`. The stable API is in
[camera_core.md](camera_core.md).

## Later

- Learned furniture edges: per camera, learn the image lines where the cat's boxes keep getting cut off (couch arms,
  desk edges) and treat a box ending there as partial, with no setup. Promising on stills; needs a real
  cluttered-room test (continuous boxes, 2- and 3-camera cases) before it's used.

## Tests

There's no test suite. Without hardware you can check imports, settings loading and path resolution (see
[README.md](README.md)). Anything touching cameras, SteamVR or the GPU needs the real setup.

To rehearse the lens calibration flow on real cameras without touching real results, run
`python -m tools.calib_intrinsics --practice` from `engine`: 4 views per camera, every camera treated as not done,
everything kept in `my_data/practice` (wiped at the start of each practice run), and "PRACTICE RUN, nothing is
saved" on screen. It never reads or writes `my_data/calibration`.

The room wizard has the same: `python -m tools.calib_room --practice` (SteamVR and Board B's tracker or
controller needed). You wave to pick the device every time, 4 stops per camera are enough, and it ends on
"Practice done" without solving (placing a camera takes 6 stops or more). Everything goes in `my_data/practice/room`
(wiped each run). It reads the lens results in `my_data/calibration` but never writes there, and it makes no
backups.
