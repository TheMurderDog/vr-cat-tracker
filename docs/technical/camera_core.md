# Camera core

Multi-webcam capture and calibration for SteamVR. It places ordinary USB webcams in your
SteamVR play space, so anything two or more cameras see can be located in 3D, in the same
coordinates as your headset and trackers.

Taken from **fbt** (a camera-based full-body tracker for VRChat) as the shared base for projects
that build on its cameras, such as a cat tracker.

## What's here

| Folder | What it does |
| --- | --- |
| `core/` | settings loading, and a log file for every run |
| `capture/` | one thread per camera: a fixed mode, locked exposure, gain and white balance, timestamps, live fps, drops and flicker |
| `calibration/` | ChArUco lens calibration (fisheye and standard models), room calibration from a SteamVR tracker with a printed marker, SteamVR pose reading, a check for cameras that moved |
| `fusion/` | triangulation across cameras with outlier rejection, One Euro filter and jump gate, lining the cameras up with the headset |
| `pose/` | a pretrained human pose model (RTMPose), to find a person's head |
| `tools/` | the programs below |

| Script (in the step folders) | |
| --- | --- |
| `0_start_here\1_install.bat` | creates `.venv` and installs `engine/requirements.txt` and `engine/requirements-pose.txt` |
| `1_connect_cameras\1_set_up_cameras.bat` | the camera setup screen: pick, name, order and turn the cameras, and save them |
| `1_connect_cameras\troubleshoot_find_cameras.bat` | which device ids open, and which give your configured mode |
| `1_connect_cameras\troubleshoot_preview_cameras.bat` | live view of every camera with fps, drops, flicker and brightness (`--seconds 600` for a soak test) |
| `2_calibrate_cameras\1_lens_calibration.bat <camera>` | lens calibration wizard for one camera |
| `2_calibrate_cameras\2_room_calibration.bat` | room calibration: places every camera in SteamVR space |
| `2_calibrate_cameras\3_check_calibration.bat` | live check: SteamVR's tracker position against what each camera sees |
| `7_if_something_moved\drift_check.bat` | reports any camera that moved since the room calibration |

All settings are in `settings/cameras.yaml`. The defaults suit a generic UVC webcam: 1280x720 MJPEG at
30 fps, with automatic exposure and white balance.

- **Calibrating:** [CALIBRATION.md](../CALIBRATION.md) walks through it from printing to checking.
- **File formats:** [FORMATS.md](FORMATS.md) describes the files, for bringing calibration from
  other tools.
- **Licenses and origin:** [NOTICE.md](../NOTICE.md).

## Requirements

- Windows 10/11 for SteamVR (the code itself is plain Python and OpenCV).
- Python 3.12, two or more UVC webcams, and SteamVR with one tracker or controller for room
  calibration.
- The pose model needs an NVIDIA GPU (driver R580 or newer).

## Using it from your own code

Run your code from `engine` (`python -m yourpackage.module`), with your package as a subfolder
next to `core/`, `capture/` and the others. Paths in settings files are relative to the top folder
(`engine`'s parent), and `core.config.REPO_ROOT` is that folder.
These names are kept stable:

```python
from core.config import load_config, get, resolve_path      # load_config(path=None); get(cfg, "a.b", default)
from core.runlog import start_run                            # log, log_file = start_run("name", cfg)
from capture.camera import camera_names, open_cameras        # cams, errors = open_cameras(cfg, log[, on_open=fn(cam)])
                                                             # cam.start(); frame, t_ns, seq = cam.latest(); cam.stop()
from tools.calib_room import load_intrinsics                 # load_intrinsics(data_dir, names)
from calibration.intrinsics import project                   # pixels of 3D points: project(pts, rvec, tvec, intrinsics)
from fusion.triangulate import Rig, triangulate              # rig = Rig(room, intrinsics); rig.normalize(c, px)
                                                             # pts, conf, used, err = triangulate(rig, views, min_score, max_reproj_px, min_views)
from fusion.filters import OneEuro, JumpGate
# optional, with requirements-pose.txt:
from pose.baseline import PoseModels, CameraPose, prepare_onnxruntime, draw
from fusion.align import head_point
```

## Focus control (experimental)

`capture/focus.py`: for cameras whose driver lets the computer set the focus (DirectShow camera control "Focus",
through OpenCV's `CAP_PROP_AUTOFOCUS` / `CAP_PROP_FOCUS`). **Experimental, not yet tried on a real autofocus
camera.** Driver answers alone aren't trusted: focus-ring cameras (e.g. "HD USB Camera", vid_32e4) report autofocus
on and accept focus values that move nothing. DirectShow reads autofocus back as 1 (on) or 2 (off).

- The setup screen's big view offers `k` when the driver claims focus control. It switches autofocus off, steps the
  focus (12 coarse, 9 fine values, in the driver's step size), measures Board B's area (the focus meter's box, or
  the whole picture), and saves the best only if the sharpness changed by at least 25%. Otherwise the focus is the
  ring: autofocus is put back and `ring` is saved, so `k` isn't offered for that camera again (to test it again,
  delete its entry from `cameras.focus`). A driver that refuses to switch autofocus off is saved as
  `stuck`. Everything is logged (`focus lock (...)` lines in the setup screen's log), for reports.
- `cameras.focus: {<camera key>: value, ring or stuck}` in `settings/cameras.yaml`. `Camera.apply_controls` sets it on
  every open, so after reconnects too (autofocus off, the value, checked by reading back; a warning if it doesn't
  take). The lens wizard warns for a `stuck` camera.
