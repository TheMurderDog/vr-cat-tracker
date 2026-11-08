# Architecture

## The pipeline

Each loop of `cat_tracker.run`:

1. **Cameras.** `capture.camera` runs one thread per camera at a fixed mode (MJPG 1280x720 by default) with locked
   exposure, gain and white balance. The loop takes each camera's latest frame and its arrival time.
   `cameras.rotate` only turns pictures for display: detection, calibration and triangulation all use the raw
   frames, so turning a camera never invalidates its calibration. Every multi-camera window (setup screen,
   preview, tracker) lays tiles out with `capture.camera.label_tile` and `tile_grid`, so they all look the same.
   Before opening, `capture.camera.resolve_ids` finds each camera by the USB device path saved in
   `cameras.devices` (Windows' DirectShow list, `capture.devices`), so ids shifting when a headset is plugged in
   don't swap cameras, and it never opens a device matching `cameras.exclude`.
   **Frame rate.** Setup, preview, calibration and, by default, the tracker (`settings/cat_tracker.yaml`
   `cameras.fps: full`) all open the cameras at `settings/cameras.yaml`'s `cameras.fps`. Each camera logs once what
   it really gives ("asked 30 fps, the camera gives 122; keeping 122"): many cameras ignore the asked speed and send
   their top speed at that size (the reference cameras: about 122 fps at 1280x720 MJPG, under DirectShow and Media
   Foundation alike). Windows decodes every frame before OpenCV hands it over, even with `CAP_PROP_CONVERT_RGB` off,
   so skipping frames in Python saves no real CPU (measured: about 64% of one core per camera either way).

   **Experimental: a lower frame rate (`cameras.fps: auto`).** The tracker only looks a few times a second, so on
   cameras that allow it, asking for `capture.camera.AUTO_FPS` (30) saves CPU and USB bandwidth. It is off by
   default because it couldn't be tested on a camera that really lowers its speed (the reference cameras can't),
   and its risks are silent: some cameras use a different sensor crop or binning at a different speed, even at the
   same size, which would make the lens and room calibration (done at full speed) wrong with no warning; and some
   drivers give black or no frames at a lower speed (the reference cameras did exactly that under Media Foundation
   at 30). When it's on, `capture.camera.Camera.open` checks the first 2 s of frames at 30 and goes back to the
   normal speed, with a log line, if fewer than 5 arrive, they're black or frozen, or they aren't the calibrated
   size. A crop change at the same size can't be detected that way: if you try it, check the tracker's view looks
   identical to the setup screen's, and that `3_check_calibration.bat` still lines up. With `auto` on, the setup
   screen also checks each camera once and says what the tracker will get. A forced number is allowed but never
   below `MIN_FPS` (30); lower is raised, with a note at startup. Results from more cameras are welcome.

   *Why 30 is the floor, and why mixed or uneven rates are fine:* nothing assumes a fixed frame rate. Each
   detection takes every camera's newest frame; the One Euro filter, `CatTrack`'s lost/fade timing, `Motion`'s
   speed and `Proximity`'s closing rate all use the detection's own time, and the jump gate and `confirm_frames`
   count detections. So the camera rate only changes how old the newest frame is, and how far apart in time the
   cameras' frames are. A synthetic room run through the real `locate`, `CatTrack`, `Motion` and `Proximity` (4
   cameras, a cat passing 35 cm from you, 8 detections a second, 1.5 px of noise, 5 runs each) gave a mean marker
   error of 5.7 / 9.0 / 18.8 cm at 0.5 / 1 / 3 m/s with every camera at 122 fps, 6.3 / 10.3 / 22.5 cm at 30 fps,
   5.9 / 9.5 / 20.1 cm with two at 30 and two at 122, 6.5 / 10.8 / 23.4 cm at an uneven 30 with dropped frames,
   and 7.1 / 11.9 / 28.0 cm at 15. Most of it is the filter's smoothing lag. Every case triangulated 100% of the
   time, warned at the same distance (set by the 8 Hz detection rate) and never flickered between states. 30 adds
   at most about 4 cm on a sprinting cat; 15 adds about 9 cm, so 30 is the floor. On the reference cameras, 30
   emulated (every 4th frame kept) gave a newest-frame age of 17 ms (5 ms at 122) and 15 ms between cameras
   (6 ms at 122), as the simulation assumed.
2. **Detect.** `cat_tracker.detector` sends every camera's frame through YOLO11 on ONNX Runtime (CUDA) in one batch,
   letterboxed to `detector.input`, and maps boxes back to full-frame pixels. It runs at `detector.rate_hz` while the
   cat is moving or close, and at `idle_rate_hz` otherwise.
3. **Locate.** `cat_tracker.locate` turns boxes into one 3D point in calibration space. Boxes whose floor point is
   outside the room (the box around the cameras plus `room_margin_m`) or higher than `max_height_m` are dropped.
   With two or more cameras, box centres are triangulated with `fusion.triangulate.Rig`, which drops a view that
   disagrees. With one camera, the ray through the bottom middle of the box meets the floor plane.
4. **Filter.** `fusion.filters` (jump gate, then One Euro filter) steadies the point. `filter.confirm_frames`
   detections in a row are needed before it is shown. After `lost_after_s` it is "last seen", and it fades over
   `fade_s`.
5. **Anchor.** `cat_tracker.anchor` holds a fit from calibration space to SteamVR's **raw** tracking space (a turn
   around the vertical plus an offset), made by pairing your head as the cameras see it (the pose model, `pose`)
   with the headset's raw pose. It is made once, during setup (headset on, about 20 s of walking), saved to
   `my_data/tracker/anchor.json` and reused by every later start (the walk-around happens only when none is saved,
   or with `--new-anchor` or `a`; `--reuse-anchor` is still accepted and does nothing). Raw space is fixed to the
   base stations, so running SteamVR's Room Setup again doesn't affect it; a bumped camera, a moved base station
   or a rebuilt base station map does. `AnchorCheck` measures it every `anchor_check.every_s` while you wear the
   headset: off by `fix_min_m` to `fix_max_m` the same way twice (within `agree_m`), it is shifted and saved
   quietly; otherwise `refit_samples` pooled sightings covering `anchor.min_spread_m` refit it quietly. Only when
   neither works does it ask for a re-anchor (a notice in VR, and the window banner). At startup it compares
   SteamVR's base station map id (`Prop_CurrentUniverseId`, saved as `universe_id` in the anchor file) and asks
   at once if it changed, unless the first check shows the anchor still fits.
6. **Show.** `cat_tracker.vrlink` converts raw space to the current standing space every update (`overlay.update_hz`)
   and places the icon, the floor ring, the edge-of-view arrow and any notice as SteamVR overlays. `cat_tracker.alert`
   decides when to warn (distance, closing speed, the cat's motion) and buzzes the controllers through SteamVR Input
   (`engine/cat_tracker/input/actions.json`).
7. **Send (optional, `--osc`).** `cat_tracker.osc` sends twelve avatar parameters to VRChat over UDP on
   `127.0.0.1:9000`, from its own thread at `vrchat.send_hz`, each time with a fresh headset pose.

Alongside: `cat_tracker.collect` saves training frames when capturing, and `cat_tracker.hardframes` saves the
moments the detector got partly wrong.

## Processes

| Process | Started by | What it does |
| --- | --- | --- |
| tracker (`cat_tracker.run`) | `2_desktop_test.bat`, `1_capture.bat`; without the app also `run_tracker.bat`, `3_run_with_vrchat.bat`, or SteamVR via `autostart.py` | everything above |
| watchdog (`cat_tracker.watchdog`) | the tracker, as a detached process, when SteamVR is in use and `health.watchdog` is on | watches the tracker's process id and `my_data/tracker/heartbeat.json`; if the tracker dies or freezes for `health.hang_s`, shows "CAT TRACKER STOPPED" in VR and buzzes |
| autostart (`engine/cat_tracker/autostart.py`) | SteamVR, registered by `install_autostart.bat` | changes into `engine` and runs `cat_app.launch --background` with `--reuse-anchor --headless` plus the saved extra arguments |
| app (`cat_app.main`, optional) | `5_play_in_vr\app\2_open_app.bat`, `cat_app.launch` (whenever the tracker starts), or SteamVR via `engine/cat_app/autostart.py` (`--background`) | the window, the SteamVR dashboard tab and the wrist widget; one copy at a time |
| tracker through the app (`cat_app.bridge`) | the app's START button, or, when the app is installed, `run_tracker.bat`, `3_run_with_vrchat.bat`, the restart scripts and SteamVR's tracker entry (all through `cat_app.launch`, which also opens the app) | runs `cat_tracker.run` unchanged in the same process, with hooks that send its picture and state to the app and take its buttons |

**Stopping.** `stop_tracker.bat` writes `my_data/tracker/stop`. The tracker checks for it about once a second,
deletes it and closes cleanly, telling the watchdog it stopped on purpose. The restart scripts write the same file,
wait up to 10 seconds for it to disappear, then start a new tracker with `pythonw.exe` (no window). If the watchdog
is showing its notice and no tracker is left, the stop file hides the notice. Closing SteamVR closes both.

**The app and the tracker.** They share no window and no port: `cat_app.link` uses a few named shared memory
blocks. The tracker side writes its status about once a second (more often, and the camera picture and heatmap,
only while the app asks), and reads the app's requests and button presses. Either can start or stop at any time;
the app shows "not running" when the status stops changing for 3 seconds. A tracker started without the app (with
`--no-app`, or before the app was installed) isn't visible to it, but the app's STOP button still stops it through the stop file.

**Health.** Inside the tracker, `cat_tracker.health` notices a camera with no new picture for
`health.camera_stale_s`, or detection failing for `health.detector_fail_s`, and shows a notice in VR. No marker
should only ever mean "no cat", never "the tracker stopped looking".

## Key design decisions

- **Raw space, not standing space.** The room calibration is in SteamVR standing space as it was on calibration day.
  Standing space moves (play space tools, Room Setup, tracking loss); raw space stays fixed to the base stations, like
  the cameras. So the cat lives in raw space and is converted to standing space every update. Dragging or turning
  the play space never moves the marker off the real cat.
- **The anchor uses your head.** No extra hardware or step: the pose model finds your eyes and ears in the cameras
  while you wear the headset, and the fit solves the room's turn as well as its offset. You must walk at least
  `anchor.min_spread_m` across so the turn can be pinned down.
- **Weak detections count only where they're expected.** Boxes down to `detector.weak_score` are used only if they
  overlap the cat's outline as projected from another camera's sighting, or from where it just was. This cuts
  flicker and gets more cameras triangulating without letting in random false hits.
- **Throw out what can't be the cat.** Anything outside the room or above furniture height is a picture on the wall
  or a reflection. Two-camera agreement and `confirm_frames` guard against one-off false hits.
- **Hard-frame mining is capped.** A moment is saved only when two or more cameras are sure of the cat and another
  that should see it didn't. Each run saves at most `hard_frames.max_moments` (150 moments, about 600 images), at most
  one every `every_s`, and stops below `min_free_gb`, so it can't fill the disk.
- **Two Python environments.** The tracker's `.venv` has pinned OpenCV, ONNX Runtime and the pose model. Training
  needs PyTorch and Ultralytics, which would clash, so it gets `.venv-train`. The tracker only ever loads `.onnx`
  files, which are data; `.pt` files (pickles that can run code) are only loaded by training.
- **Nothing elevated, nothing listening.** No admin rights anywhere. No open ports. The only network output is OSC to
  `127.0.0.1`. The app talks to the tracker through shared memory, not the network.
