# Camera core

Multi-webcam capture and calibration for SteamVR. It places ordinary USB webcams in your
SteamVR play space, so anything two or more cameras see can be located in 3D, in the same
coordinates as your headset and trackers.

Taken from **fbt** (a camera-based full-body tracker for VRChat) as the shared base for projects
that build on its cameras, such as a cat tracker.

## What's here

| Folder | What it does |
| --- | --- |
| `core/` | `config.yaml` loading, and a log file for every run |
| `capture/` | one thread per camera: a fixed mode, locked exposure, gain and white balance, timestamps, live fps, drops and flicker |
| `calibration/` | ChArUco lens calibration (fisheye and standard models), room calibration from a SteamVR tracker with a printed marker, SteamVR pose reading, a check for cameras that moved |
| `fusion/` | triangulation across cameras with outlier rejection, One Euro filter and jump gate, lining the cameras up with the headset |
| `pose/` | *optional:* a pretrained human pose model (RTMPose), to find a person's head |
| `tools/` | the programs below |

| Script | |
| --- | --- |
| `setup.bat` | creates `.venv` and installs `requirements.txt` (`setup.bat pose` adds the pose model) |
| `probe_cameras.bat` | which device ids open, and which give your configured mode |
| `preview.bat` | live view of every camera with fps, drops, flicker and brightness (`--seconds 600` for a soak test) |
| `make_boards.bat` | printable lens-calibration board and tracker marker (PDF, exact size) |
| `calib_intrinsics.bat <camera>` | lens calibration wizard for one camera |
| `calib_room.bat` | room calibration: places every camera in SteamVR space |
| `calib_check.bat` | live check: SteamVR's tracker position against what each camera sees |
| `drift_check.bat` | reports any camera that moved since the room calibration |

All settings are in `config.yaml`. The defaults suit a generic UVC webcam: 1280x720 MJPEG at
30 fps, with automatic exposure and white balance.

- **Calibrating:** [CALIBRATION.md](CALIBRATION.md) walks through it from printing to checking.
- **File formats:** [FORMATS.md](FORMATS.md) describes the files, for bringing calibration from
  other tools.
- **Licenses and origin:** [NOTICE.md](NOTICE.md).

## Requirements

- Windows 10/11 for SteamVR (the code itself is plain Python and OpenCV).
- Python 3.12, two or more UVC webcams, and SteamVR with one tracker or controller for room
  calibration.
- The optional pose model needs an NVIDIA GPU (driver R580 or newer).

## Using it from your own code

Run your code from this folder (`python -m yourpackage.module`), with your package as a subfolder
next to `core/`, `capture/` and the others. Paths in config files are relative to this folder.
These names are kept stable:

```python
from core.config import load_config, get, resolve_path      # load_config(path=None); get(cfg, "a.b", default)
from core.runlog import start_run                            # log, log_file = start_run("name", cfg)
from capture.camera import camera_names, open_cameras        # cams, errors = open_cameras(cfg, log)
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
