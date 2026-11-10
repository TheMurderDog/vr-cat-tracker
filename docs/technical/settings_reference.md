# Settings reference

Every key in the two settings files, with its default and what it does. This page is generated from the files'
own comments, so the comments in `settings/cameras.yaml` and `settings/cat_tracker.yaml` are the source of truth.
Paths are relative to the top folder unless absolute.

- `settings/cameras.yaml` is read by every program (`core.config.load_config`). The cat tracker never writes it.
- `settings/cat_tracker.yaml` is read by the cat tracker on top of it (`cat_tracker.settings.load`). Its `logging`
  section replaces the camera one for the tracker's runs, its `cameras` section overrides camera settings for the
  tracker's runs only, and the rest becomes `cfg["cat"]`. `3_train.bat` rewrites `detector.model` and
  `detector.cat_class` in it (after a backup to `my_data/backups`).

## settings/cameras.yaml

| Key | Default | What it does |
| --- | --- | --- |
| `logging` |  |  |
| `logging.dir` | `my_data/logs/cameras` |  |
| `logging.console_level` | `INFO` | DEBUG, INFO, WARNING, ERROR |
| `logging.file_level` | `DEBUG` |  |
| `logging.keep_last` | `100` | oldest run logs beyond this count are deleted |
| `gpu` |  |  |
| `gpu.device_id` | `0` | CUDA device index (used by the pose model) |
| `onnxruntime` |  | only used by the pose model (installed by 0_start_here\1_install.bat) |
| `onnxruntime.providers` | `[CUDAExecutionProvider, CPUExecutionProvider]` |  |
| `onnxruntime.preload_cuda_dlls` | `true` | load CUDA/cuDNN from the nvidia-* pip packages, no CUDA Toolkit install needed |
| `steamvr` |  |  |
| `steamvr.tracking_universe` | `standing` | room calibration and everything after it is in SteamVR standing space |
| `cameras` |  |  |
| `cameras.backend` | `dshow` | dshow (Windows DirectShow), msmf (Windows Media Foundation) or any. On Windows, dshow usually reaches the highest frame rates and has the driver settings dialog. |
| `cameras.ids` | `[]` | OpenCV device ids, one per camera; 1_connect_cameras\1_set_up_cameras.bat sets them |
| `cameras.names` | `[]` | one name per id, same order. Naming them by wall (north, east...) helps. |
| `cameras.blocky_limit` | `2.2` (not in the file) | frames whose bottom third is blockier than this (`capture.camera.jpeg_blocky`: damaged on the way, short of USB bandwidth) are dropped and counted |
| `cameras.keys` | (not set: the names) | what each camera's calibration is filed under, kept by the setup screen when a camera is renamed or reordered (a new camera gets `cam-` and 6 hex digits). Don't edit it. |
| `cameras.exclude` | `eTronVideo`, `vid_28de`, `Valve`, `Vive`, `Oculus`, `Quest`, `Rift`, `OBS Virtual`, `Virtual Camera` | devices never opened: part of a name or device path (VR headset and virtual cameras) |
| `cameras.devices` | `[]` | each camera's USB device, set by the setup screen: finds it again if its id changes |
| `cameras.focus` | (none) | experimental: per camera key, a focus locked by the setup screen's `k` (autofocus off, this value), `ring` (its focus is its ring: `k` hidden; delete the entry to test again) or `stuck` |
| `cameras.width` | `1280` | the mode every camera is opened in (lens calibration is only valid for this size) |
| `cameras.height` | `720` |  |
| `cameras.fps` | `30` | asked of each camera. Many only offer their top speed at a size (e.g. 120 at 1280x720) and ignore this: that's fine, the tracker uses the newest frame |
| `cameras.fourcc` | `MJPG` | compressed USB mode; needed for 720p and up on most UVC webcams |
| `cameras.require_exact_mode` | `true` | refuse a device that can't give exactly width x height in fourcc (a different camera took its id) |
| `cameras.rotate` | `none` | none, cw90, ccw90 or 180; or a list, one per camera. For display only; calibration uses raw frames |
| `cameras.exposure_ms` | `null` | null = automatic exposure. Fixed exposure (e.g. 7.8) keeps brightness steady between cameras |
| `cameras.exposure_units` | `log2_s` | how exposure_ms is sent: log2_s (Windows dshow/msmf) or 100us (Linux V4L2) |
| `cameras.auto_exposure_off_value` | `0.25` | value OpenCV's Windows backends take as "manual exposure" (V4L2 usually 1) |
| `cameras.gain` | `null` | null = leave the driver's value |
| `cameras.white_balance_k` | `null` | e.g. 5600 to lock white balance so colours match between cameras; null = leave automatic |
| `cameras.flicker_window_frames` | `90` | frames for the preview's flicker meter (3 s at 30 fps) |
| `cameras.open_delay_s` | `0.5` | pause between opening cameras (some USB hubs dislike opening all at once) |
| `preview` |  |  |
| `preview.tile_height` | `480` | pixels per camera tile in the preview and calibration windows |
| `preview.log_every_s` | `5` | stats line per camera in the run log |
| `calibration` |  |  |
| `calibration.dir` | `my_data/calibration` | boards, captured frames and calibration results (keep out of git) |
| `calibration.print_dpi` | `300` |  |
| `calibration.voice_volume` | `0.8` | loudness of the calibration wizards' voice, 0 to 1 |
| `calibration.focus_in_focus_at` | `0.85` | the setup screen's focus meter says "in focus" this far from the blurriest to the sharpest seen lately |
| `calibration.focus_hold_s` | `0.7` | and held this long (seconds) |
| `calibration.intrinsics` |  | lens calibration (2_calibrate_cameras\1_lens_calibration.bat) |
| `calibration.intrinsics.voice` | `true` | spoken prompts and beeps (v turns them off while it runs; --quiet starts without) |
| `calibration.intrinsics.target_views` | `40` | views captured before it calibrates by itself |
| `calibration.intrinsics.finish_when_covered` | `30` | ...or this many, once every area of the picture is covered |
| `calibration.intrinsics.min_corners` | `8` | ChArUco corners a view needs |
| `calibration.intrinsics.still_px` | `1.5` | mean corner movement between frames that counts as "held still" |
| `calibration.intrinsics.novelty_px` | `40` | a view must differ from every earlier one by this many pixels on average |
| `calibration.intrinsics.models` | `[fisheye, rational]` | both are tried; the lower RMS wins (fisheye gets a 5% preference) |
| `calibration.intrinsics.outlier_factor` | `3.0` | views with error over this x the median are dropped and it recalibrates |
| `calibration.intrinsics.max_rms_px` | `0.8` | FIT GOOD below this |
| `calibration.intrinsics.min_coverage` | `0.6` | and with at least this share of the 8x6 image grid covered |
| `calibration.intrinsics.stretch_correct_above` | `0.005` | a printout stretched one way by this much (0.5%) or more is corrected for (0 turns the check off) |
| `calibration.intrinsics.stretch_reprint_above` | `0.03` | ...and by this much (3%) or more: CHECK YOUR PRINT (reprint) instead of FIT GOOD |
| `calibration.intrinsics.refine_markers` | `true` | re-find markers the first pass missed, using the board layout (more range) |
| `calibration.intrinsics.error_correction` | `0.8` | share of a marker's correctable bit errors to accept (OpenCV default 0.6) |
| `calibration.intrinsics.pixels_per_cell` | `8` | sampling per marker bit (OpenCV default 4) |
| `calibration.boards` |  |  |
| `calibration.boards.small` |  | Board A: the lens-calibration checkerboard, one sheet of paper |
| `calibration.boards.small.squares` | `[5, 7]` |  |
| `calibration.boards.small.square_mm` | `34.0` | as designed; a print a little smaller overall needs no change here (only a one-way stretch matters: reprint) |
| `calibration.boards.small.marker_mm` | `25.5` |  |
| `calibration.boards.small.dictionary` | `DICT_5X5_250` |  |
| `calibration.boards.small.first_marker_id` | `0` |  |
| `calibration.boards.small.page_mm` | `[215.9, 279.4]` | US letter; for A4 use [210.0, 297.0] |
| `calibration.room` |  | room calibration (2_calibrate_cameras\2_room_calibration.bat): a SteamVR tracker carrying a printed marker |
| `calibration.room.marker_dictionary` | `DICT_4X4_50` | big cells, so it still reads from across the room |
| `calibration.room.marker_id` | `7` |  |
| `calibration.room.marker_mm` | `160` | fits letter and A4. Fix the tracker rigidly above Board B's edge, sensors clear |
| `calibration.room.device_serial` | `null` | Board B's tracker or controller is picked by waving it (remembered in `my_data/calibration/room_device.json`); a serial number here always uses that one |
| `calibration.room.voice` | `true` | spoken prompts and beeps while you walk with Board B (--quiet: without) |
| `calibration.room.vr_rate_hz` | `250` |  |
| `calibration.room.detect_every_n_frames` | `3` | marker detection on every Nth frame per camera |
| `calibration.room.frame_latency_ms` | `15` | rough time from exposure to frame arrival; the tracker pose is read this much earlier |
| `calibration.room.still_speed_m_s` | `0.05` | only use moments when the tracker is nearly still (camera timestamps jitter) |
| `calibration.room.min_spacing_m` | `0.05` | and at least this far from the previous kept moment for that camera |
| `calibration.room.target_per_camera` | `25` | still moments per camera; one stop counts for every camera that sees it |
| `calibration.room.stuck_after_s` | `60` | no new stop for this long, and every camera has `stuck_min_per_camera`: it offers to finish (a 10 s countdown; any new stop cancels it) |
| `calibration.room.stuck_min_per_camera` | `12` |  |
| `calibration.room.max_rms_px` | `3.0` | FIT GOOD below this |
| `calibration.room.ok_px` | `4.5` | FIT OK (a little less precise, fine to use) below this; above it, FIT NOT GOOD |
| `calibration.room.retry_rounds` | `2` | walks again for a camera that isn't FIT GOOD at most this often, and only while its error keeps dropping (then it says what to do instead: usually redo its lens) |
| `calibration.room.check_max_px` | `6.0` | 3_check_calibration.bat: a camera is FIT GOOD when its median gap is at most this |
| `calibration.drift` |  |  |
| `calibration.drift.max_shift_px` | `2.0` | drift_check: a picture shifted more than this (most of its 12 tiles agreeing) has moved a little |
| `calibration.drift.recalibrate_px` | `5.0` | ...and more than this needs its room calibration redone (about 0.4 degrees) |
| `calibration.drift.min_confidence` | `0.2` | the room calibration's own drift check: below this the frames are too different to compare |
| `pose` |  | the pose model the cat tracker's anchor uses (installed by 0_start_here\1_install.bat): RTMPose via rtmlib, Halpe 26 keypoints Downloaded on first use from OpenMMLab (to ~/.cache/rtmlib). See NOTICE.md for their terms. |
| `pose.detector_url` | `https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip` |  |
| `pose.detector_input` | `[640, 640]` |  |
| `pose.detector_score` | `0.5` |  |
| `pose.pose_url` | `https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7-halpe26_700e-256x192-4d3e73dd_20230605.zip` |  |
| `pose.pose_input` | `[192, 256]` | width, height |
| `pose.keypoint_score` | `0.3` | a keypoint below this counts as not seen |
| `pose.min_visible_keypoints` | `6` | fewer than this and the person counts as lost (the detector runs again) |
| `pose.redetect_every_n` | `600` | run the detector anyway every N frames per camera (it is slow, ~30 ms) |
| `pose.cudnn_algo_search` | `EXHAUSTIVE` | GPU kernel choice; EXHAUSTIVE is slower to start, faster to run |
| `pose.cuda_graph` | `true` | replay the pose model as one recorded GPU graph (falls back if it can't) |
| `pose.batch` | `4` | crops per GPU run with the CUDA graph; set to your number of cameras |
| `pose.crop_margin` | `0.15` | next crop = last keypoints plus this share of their size |
| `fusion` |  |  |
| `fusion.keypoint_score` | `0.3` | views below this score don't vote for a point |
| `fusion.min_views` | `2` | cameras that must see a point to place it |
| `fusion.max_reprojection_px` | `15` | a view further than this from the 3D point is dropped as wrong |
| `fusion.min_cutoff` | `1.5` | One Euro filter: lower = smoother when still, more lag |
| `fusion.beta` | `0.5` | One Euro filter: higher = less lag when moving fast |
| `fusion.d_cutoff` | `1.0` |  |
| `fusion.max_jump_m` | `0.4` | a point leaping further than this in one update is ignored as a mistake... |
| `fusion.jump_accept_after` | `5` | ...unless it stays there this many updates in a row |
| `fusion.headset_to_head_m` | `[0.0, -0.02, 0.06]` | typical spot of the seen eyes/ears relative to the headset, in its own frame |

## settings/cat_tracker.yaml

| Key | Default | What it does |
| --- | --- | --- |
| `logging` |  |  |
| `logging.dir` | `my_data/logs/cat_tracker` | the cat tracker's own logs, so the core's logs are never pruned or mixed |
| `logging.console_level` | `INFO` |  |
| `logging.file_level` | `DEBUG` |  |
| `logging.keep_last` | `50` |  |
| `cameras` |  | overrides of settings/cameras.yaml's camera settings, for the cat tracker's runs only |
| `cameras.fps` | `full` | `full`: the same speed as setup and calibration (`settings/cameras.yaml`). `auto` is EXPERIMENTAL and deliberately not named in the settings file: it asks each camera for 30 fps to save CPU, falling back to the normal speed if those frames don't arrive, are black or frozen, or aren't the calibrated size; a camera that changes its sensor crop at 30 would still silently break the calibration, so check the view and `3_check_calibration.bat`. A number forces one speed, never below 30. Details and test results: architecture.md, Frame rate |
| `reset_white_balance` | `true` | with a fixed white_balance_k: at start, toggle auto white balance on and off, then set it again (some drivers keep an old value otherwise). Does nothing when white balance is automatic |
| `detector` |  | the stock COCO model to start (cats are class 15; 3_first_test\1_get_stock_model.bat gets it). Train it on YOUR cat (4_teach_it_your_cat); 3_train.bat then switches this to model: my_data/models/cat_finetuned_half.onnx  and  cat_class: 0 |
| `detector.model` | `my_data/models/yolo11s.onnx` |  |
| `detector.input` | `960` | long side fed to the model (1280x720 -> 960x544); 640 missed small cats in tests, 1280 is slower |
| `detector.cat_class` | `15` |  |
| `detector.score` | `0.2` | lowest confidence that counts as a cat; the room and height checks and confirm_frames weed out the extra false hits this lets in |
| `detector.weak_score` | `0.08` | weaker boxes still count where it's expected: next to another camera's sighting or where it just was (cuts flicker, gets more cameras to triangulate) |
| `detector.gamma` | `1.0` | below 1 brightens shadows before detection (try 0.8 if a camera is still dark) |
| `detector.nms_iou` | `0.5` |  |
| `detector.min_box_px` | `12` | boxes smaller than this (in the full frame) are ignored |
| `detector.rate_hz` | `8` | detections per second while it's moving or close to you (all four cameras in one GPU run) |
| `detector.idle_rate_hz` | `3` | ...and while it's still, asleep or out of the room, which is most of the time. Its marker still follows your head smoothly either way, see overlay.update_hz |
| `detector.tripwire_change` | `6.0` | EXPERIMENTAL: at the idle rate, the cat's spot is checked 30 times a second between detections; this much change (grey levels) runs the detector at once (cat_tracker/tripwire.py) |
| `detector.full_rate_within_m` | `3.0` | EXPERIMENTAL: this close to you: the full rate, still or not |
| `locate` |  |  |
| `locate.min_views` | `2` | cameras that must agree to triangulate it |
| `locate.max_reprojection_px` | `40` | box centres seen from different sides are not the exact same point, so this is loose |
| `locate.floor_y_m` | `0.0` | floor height in calibration space (room.json was solved in SteamVR standing space) |
| `locate.body_height_m` | `0.15` | height of a cat's middle when only one camera sees it (placed on the floor) |
| `locate.floor_depth_m` | `0.2` | with one camera, its middle is this much further away than the bottom edge of its box |
| `locate.max_height_m` | `1.0` | higher than this (top of a dresser or desk) is a picture on the wall, not the cat |
| `locate.room_margin_m` | `0.15` | the room = the box around the four cameras plus this |
| `locate.outline_radius_m` | `0.22` | its outline when projecting where it should appear in a camera: a cylinder this wide... |
| `locate.outline_half_height_m` | `0.15` | ...and twice this tall |
| `locate.weak_iou` | `0.3` | how much a weak box must overlap that outline to count |
| `filter` |  |  |
| `filter.min_cutoff` | `1.0` | One Euro filter (the camera code's): lower = steadier, more lag |
| `filter.beta` | `0.8` | higher = less lag when it runs |
| `filter.d_cutoff` | `1.0` |  |
| `filter.max_jump_m` | `1.0` | a position this far from the last one is ignored as a mistake... |
| `filter.jump_accept_after` | `2` | ...unless it repeats this many detections in a row |
| `filter.confirm_frames` | `2` | detections in a row before it is shown (guards against one-off false hits; 0.4 s at 5 Hz) |
| `filter.lost_after_s` | `1.0` | no detection for this long: it is "last seen" and its marker dims |
| `filter.fade_s` | `8.0` | the last-seen marker fades out over this long, then hides |
| `anchor` |  | lines camera space up with SteamVR's raw tracking space (unaffected by play space moves) |
| `anchor.file` | `my_data/tracker/anchor.json` |  |
| `anchor.samples` | `300` | head sightings (headset on, cameras seeing you) to collect |
| `anchor.min_spread_m` | `0.8` | you must walk around at least this far, or the turn of the room can't be pinned down |
| `anchor.timeout_s` | `90` |  |
| `anchor.max_residual_m` | `0.06` | median fit error above this is reported as a bad anchor |
| `overlay` |  |  |
| `overlay.icon` | `engine/cat_tracker/assets/cat.png` |  |
| `overlay.icon_close` | `engine/cat_tracker/assets/cat_close.png` |  |
| `overlay.icon_rest` | `engine/cat_tracker/assets/cat_rest.png` | still for rest_after_s: eyes closed, z z (CatState 1 in VRChat) |
| `overlay.icon_move` | `engine/cat_tracker/assets/cat_move.png` | moving at move_speed or faster |
| `overlay.rest_after_s` | `120` | 2 minutes still before it counts as asleep (was 20 s) |
| `overlay.move_speed` | `0.2` | m/s: faster than this for move_start_s and it's moving (CatState 2)... |
| `overlay.move_start_s` | `0.4` |  |
| `overlay.move_stop_speed` | `0.12` | ...until it's slower than this for move_stop_s (two thresholds, so jitter can't flicker it) |
| `overlay.move_stop_s` | `1.0` |  |
| `overlay.smooth_s` | `0.15` | its marker and the snake ease toward each new detection over about this long |
| `overlay.still_speed` | `0.1` | below this it counts as still (m/s) |
| `overlay.speed_window_s` | `1.0` | its speed is how far it got over this long |
| `overlay.heading_window_s` | `1.5` | its heading (VRChat CatRoomYaw) compares where it was this long ago with now |
| `overlay.heading_min_move_m` | `0.08` | ...and only turns once it has covered this much (averaged, so jitter cancels); lower = turns on slower walks, but too low lets a still cat's jitter turn it |
| `overlay.heading_smooth_s` | `0.3` | then eases toward the new direction over about this long |
| `overlay.ring` | `engine/cat_tracker/assets/ring.png` |  |
| `overlay.icon_width_m` | `0.28` |  |
| `overlay.icon_lift_m` | `0.30` | icon floats this far above its middle, so it isn't hidden in the floor |
| `overlay.ring_width_m` | `0.55` | flat ring on the floor under it |
| `overlay.lost_alpha` | `0.6` | brightness of the last-seen marker when it starts fading |
| `overlay.update_hz` | `30` | how often the marker, edge arrow and VRChat offset are re-placed from your head pose |
| `alert` |  | when to warn: a small arrow at the edge of your view pointing toward it, and its red icon |
| `alert.underfoot_m` | `1.0` | this close: set to warn even when the cat is still or asleep (was 0.5: too late, 2026-10-30) |
| `alert.radius_m` | `1.8` | this close and it's moving: warn |
| `alert.ttc_s` | `2.5` | it (or you) closing in fast enough to meet within this many seconds: warn early... |
| `alert.max_warn_m` | `4.0` | ...from up to this far away |
| `alert.min_closing_speed` | `0.2` | m/s; slower than this doesn't count as closing in |
| `alert.still_speed` | `0.15` | m/s; within radius_m but slower than this (napping) doesn't warn |
| `alert.closing_smooth_s` | `0.4` |  |
| `alert.buzz` | `true` | controller vibration once each time the warning comes on (the arrow and red icon); SteamVR Input, see input/actions.json |
| `alert.buzz_pattern` | `LRLR` | one pulse per letter, L = left controller, R = right |
| `alert.buzz_total_s` | `1.0` | the whole pattern takes this long |
| `alert.buzz_s` | `0.15` | each pulse |
| `alert.buzz_amplitude` | `0.6` | 0-1 |
| `alert.buzz_rearm_s` | `1.0` | the warning must be off this long before the next buzz, so a flicker at the edge doesn't buzz twice; while it stays close (cuddles) it stays quiet |
| `alert.image` | `engine/cat_tracker/assets/edge_arrow.png` |  |
| `alert.edge_angle_deg` | `32` | how far from the middle of your view the arrow sits (about the edge of a clear view) |
| `alert.distance_m` | `1.0` | the arrow is drawn this far in front of your eyes... |
| `alert.width_m` | `0.07` | ...and this wide (0.07 m at 1 m is about 4 degrees) |
| `alert.alpha` | `0.9` |  |
| `anchor_check` |  | while running, every few minutes: is the saved anchor still right? Fixes it quietly when it can |
| `anchor_check.enabled` | `true` |  |
| `anchor_check.first_after_s` | `30` |  |
| `anchor_check.every_s` | `180` |  |
| `anchor_check.recheck_s` | `20` | while the anchor looks off or unconfirmed, check this often instead, until it's settled |
| `anchor_check.samples` | `20` | head sightings per check (headset on, cameras seeing you) |
| `anchor_check.window_s` | `20` | give up on a check after this long without enough sightings, try again later |
| `anchor_check.fix_min_m` | `0.03` | off by less than this: fine, nothing to do |
| `anchor_check.fix_max_m` | `0.30` | off by up to this, the same way in two checks in a row: shifted quietly to fit (no notice) |
| `anchor_check.agree_m` | `0.04` | how closely those two checks must agree before it shifts |
| `anchor_check.refit_samples` | `100` | off in a way a shift can't fix: redo the anchor quietly from this many sightings of your normal moving around (they must cover anchor.min_spread_m); a notice only if it can't |
| `anchor_check.max_scatter_m` | `0.08` | sightings scattered more than this are ignored (someone else in view, headset not worn) |
| `anchor_check.image` | `engine/cat_tracker/assets/anchor_warning.png` |  |
| `health` |  | tries to make a missing marker mean "no cat seen" rather than "the tracker stopped looking"; it can't guarantee that |
| `health.camera_stale_s` | `2.0` | a camera with no new picture for this long: a notice in VR, and its old picture is ignored |
| `health.detector_fail_s` | `3.0` | detection failing for this long: a notice in VR |
| `health.watchdog` | `true` | a small separate process (engine\cat_tracker\watchdog.py) that shows "CAT TRACKER STOPPED" in VR and buzzes the controllers if the tracker crashes, is killed or freezes |
| `health.hang_s` | `3` | no sign of life from the tracker for this long counts as frozen. The heartbeat is written twice a second; known slow steps (the first detections, loading the pose model for the anchor check) tell the watchdog to wait longer. A notice stays up at least 4 s so it can be read. Updates slower than 1 s are logged as "Slow update" |
| `hard_frames` |  | saves moments the model struggled with, for the next training round (see hardframes.py) |
| `hard_frames.enabled` | `true` | only when 2+ cameras are sure of it and another camera that should see it didn't |
| `hard_frames.every_s` | `3.0` | at most one moment (4 images) this often |
| `hard_frames.max_moments` | `150` | per tracker run: 600 images, about 100 to 150 MB |
| `hard_frames.min_free_gb` | `10` | stop below this much free disk space |
| `hard_frames.min_sure_cameras` | `2` |  |
| `vrchat` |  | 6_optional_vrchat\3_run_with_vrchat.bat: its position for the avatar's cat prop (see osc.py) |
| `vrchat.host` | `127.0.0.1` |  |
| `vrchat.port` | `9000` | VRChat's OSC input |
| `vrchat.range_m` | `4.0` | CatAhead and CatRight are metres divided by this (the avatar must use the same) |
| `vrchat.send_hz` | `60` | every parameter, this often, each time with the headset pose read right then |
| `vrchat.stick_anchor` |  | EXPERIMENTAL: hold the cat's reference point still while the thumbsticks rest (stick_anchor.py) |
| `vrchat.stick_anchor.enabled` | `false` | true only with an avatar prefab that has CatAnchorMode (docs\vrchat_avatar.md) |
| `vrchat.stick_anchor.stick_deadzone` | `0.2` | a thumbstick counts as pushed past this (0..1) |
| `vrchat.stick_anchor.stick_min_s` | `0.1` | ...for at least this long, so a brushed stick doesn't count |
| `vrchat.stick_anchor.settle_s` | `0.3` | after the sticks are let go, wait this long before looking for a steady head |
| `vrchat.stick_anchor.still_turn_dps` | `15` | steady head: turning slower than this (degrees a second)... |
| `vrchat.stick_anchor.still_move_mps` | `0.15` | ...and moving slower than this (metres a second) |
| `vrchat.stick_anchor.average_s` | `0.5` | steady this long; the anchor is the head's average pose over it |
| `vrchat.stick_anchor.refresh_s` | `30` | while anchored and steady, anchor again this often, for people who join later (0 = off) |
| `capture` |  | 4_teach_it_your_cat\1_capture.bat (or c in a tracker window): frames saved in my_data/captures |
| `locate.partial_ratio` | `0.6` | with 3+ cameras seeing the cat: a camera whose box is under this share of the size a cat has at the position the others give (part of it hidden behind furniture or the picture edge) counts less in the triangulation, by the square of that share. Tested on the old furnished setup: one box cut to a 30-45% slice pulled the position 3.4-4.1 cm today, 0.8-0.9 cm with this. Not used with 2 cameras (no clear gain there). 0 = off |
| `capture.every_s` | `2.0` | one frame from each camera this often (10 minutes = 1200 images) |
| `capture.enough_moments` | `150` | a rough guide, not a rule: "enough for a first model" (on screen, said once; it never suggests stopping) after the stock model boxed the cat in this many moments. Training warns under 50 images with the cat and does well from a few hundred; 150 moments usually give 300 or more (the cat is boxed in about 2 of 4 cameras, autolabel adds more) |
| `capture.enough_spots` | `3` | and in at least this many different 75 cm squares of the floor, so it isn't all one nap |
| `capture.min_free_gb` | `5` | stop capturing below this much free disk space |
| `label.helper_model` | not set | the model the labelling helpers use (the click snap in 2_label, autolabel's crop), e.g. a trained model from another copy; with `label.helper_cat_class` (default 0). The newest of it and the trained models in `my_data/models` (the helper 2_label trains, or 3_train's) is used; none: `detector.model`. The tracker always uses `detector.model` |
| `autolabel` |  | 4_teach_it_your_cat\2_label.bat, by itself on a new session: fill in boxes the stock model missed in a capture session |
| `autolabel.still_m` | `0.3` | two sightings closer than this... |
| `autolabel.max_gap_s` | `8.0` | ...and this close in time: it stayed put, so the moments between get its position |
| `autolabel.radius_m` | `0.22` | its outline for projecting into other cameras: a cylinder this wide... |
| `autolabel.half_height_m` | `0.15` | ...and twice this tall, around its middle |
| `autolabel.refine_score` | `0.05` | a weak stock-model box (this confident or more) overlapping the outline is used instead; 0 = off |
| `autolabel.refine_iou` | `0.3` |  |
| `preview` |  |  |
| `preview.show_every_n` | `1` | redraw the desktop window every Nth detection |
| `preview.tile_height` | `360` |  |
