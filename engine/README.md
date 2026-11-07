# engine

All the code. You never need to open this folder to set up the tracker: the scripts in the numbered folders run it
for you.

| Folder | What it does |
| --- | --- |
| `core` | settings loading, and a log file for every run |
| `capture` | one thread per camera: fixed mode, locked exposure, gain and white balance, timestamps, fps, drops, flicker |
| `calibration` | lens calibration, room calibration from a SteamVR tracker with a printed marker, SteamVR pose reading, the moved-camera check |
| `fusion` | triangulation across cameras, the One Euro filter and jump gate, lining the cameras up with the headset |
| `pose` | the pretrained human pose model (RTMPose), used to find your head for the anchor |
| `tools` | the camera programs run by steps 1, 2 and 7 |
| `cat_tracker` | the cat tracker itself (steps 3 to 6), with its overlay images (`assets`) and SteamVR input files (`input`) |
| `requirements*.txt` | the Python packages, at fixed versions: `requirements.txt` and `requirements-pose.txt` for the main `.venv`, `cat_tracker/requirements-train.txt` for `.venv-train` |
| `make_train_env.bat` | creates `.venv-train`, used by `3_first_test\1_get_stock_model.bat` and `4_teach_it_your_cat\3_train.bat` |

Every step script changes into this folder and runs `python -m <package>.<module>`, for example
`python -m tools.probe_cameras`, with the Python in the top folder's `.venv`. Paths in the settings files are relative
to the top folder. [docs/technical/camera_core.md](../docs/technical/camera_core.md) describes the camera code for building your own
projects on it.
