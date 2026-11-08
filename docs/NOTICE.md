# Origin and third-party notices

## Origin

All the code in this folder was written for **fbt**, a private camera-based full-body tracking
project for VRChat, and copied out here so it can be published on its own. It contains no code
copied from other projects. These parts are new implementations of published methods:

- **One Euro filter** (`fusion/filters.py`): the method of Casiez, Roussel and Vogel, "1 € Filter:
  A Simple Speed-based Low-pass Filter for Noisy Input in Interactive Systems", CHI 2012. It is
  written from the paper, not copied.
- **Triangulation** (`fusion/triangulate.py`): the standard weighted direct linear transform (DLT).
- **PDF writer** (`calibration/board.py`): a minimal one written for this project. The PDF format
  is an open standard.
- **Halpe 26 keypoint names** (`pose/baseline.py`): the keypoint list of the Halpe dataset, needed
  to read the pose model's output.

The project is published under **AGPL-3.0** (see `LICENSE`).

## Python dependencies

These are installed with pip and not included in this folder. All of their licenses allow use
from an AGPL-3.0 project.

| Package | Used for | License |
| --- | --- | --- |
| opencv-python (OpenCV) | capture, ArUco/ChArUco, calibration | Apache-2.0 (OpenCV 4.5 and newer) |
| numpy | everything | BSD-3-Clause |
| scipy | room calibration solver | BSD-3-Clause |
| PyYAML | the settings files | MIT |
| openvr (pyopenvr) | tracker poses from SteamVR | BSD-3-Clause (Valve's OpenVR SDK it wraps: BSD-3-Clause) |
| onnxruntime-gpu | running the pose model | MIT (its CUDA/cuDNN pip packages are under NVIDIA's own license terms) |
| rtmlib | pose model wrapper | Apache-2.0 |

## Calibration voice (`engine/tools/voice.py`)

The lens and room calibration wizards speak their prompts with an offline voice:

| Part | Where it comes from | License |
| --- | --- | --- |
| piper-tts 1.8.0 (Piper, with the espeak-ng phonemizer it includes) | PyPI, installed by `0_start_here\1_install.bat` | GPL-3.0-or-later (compatible with this project's AGPL-3.0) |
| pathvalidate 3.3.1 | PyPI, a Piper dependency | MIT |
| the voice `en_US-ljspeech-medium` | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) v1.0.0, downloaded by `engine/tools/get_voice.py` and checked against its SHA-256 | MIT (the voice model); trained on the [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) recordings, which are in the public domain |

If Piper or the voice is missing, the wizards use Windows' own voice (System.Speech), and failing that, beeps only.

## Pose model (`pose/baseline.py`), used by the anchor walk

`pose/baseline.py` uses two pretrained models from OpenMMLab's MMPose project, through rtmlib:

- **RTMPose-m**, trained on seven public pose datasets ("body7"), with Halpe 26 keypoints.
- **YOLOX-m**, a person detector trained on Human-Art.

The URLs are in `settings/cameras.yaml` under `pose`.

**The model files are not included in this repository.** rtmlib downloads them from OpenMMLab's
server the first time they're used.

- **Code license.** MMPose (which produced the models) and rtmlib are both **Apache-2.0**, which
  is compatible with AGPL-3.0.
- **Weights license.** No separate license statement for the model weights themselves could be
  found. The datasets they were trained on have their own terms, and some of them are research or
  non-commercial only.

Downloading the models at run time, rather than bundling them, keeps them out of this repository.
Check those dataset terms before any commercial use, or before putting the model files into the
repository.

The cat tracker needs it for the anchor walk in step 5 (`0_start_here\1_install.bat` installs it). Capture,
both calibrations, triangulation and filtering work without it.
`fusion/align.py` reads only the keypoint names from `pose/baseline.py`, not the models.

## Cat tracker (`engine/cat_tracker/`)

Also written for this project; no code copied from elsewhere. Extra dependencies:

| Package | Used for | License |
| --- | --- | --- |
| ultralytics (YOLO11) | training the cat detector (`3_train.bat` and `1_get_stock_model.bat`, its own environment `.venv-train`) | AGPL-3.0 |
| torch, torchvision | training | BSD-3-Clause |
| onnx, onnxslim, onnxconverter-common | exporting the trained model | Apache-2.0 / MIT |
| onnxruntime-gpu | running the detector | MIT |

The YOLO11 model weights (`yolo11s.pt`, downloaded by Ultralytics) are AGPL-3.0. No model files are included.
Ultralytics' anonymous usage events are switched off in this project's processes (see SECURITY.md).

## The app (`engine/cat_app/`)

Also written for this project; no code copied from elsewhere. It's optional (`5_play_in_vr\app\1_install_app.bat`)
and adds one package to the tracker's `.venv`:

| Package | Used for | License |
| --- | --- | --- |
| PySide6-Essentials 6.12.0 (Qt for Python, with the Qt libraries it includes) | the window, the SteamVR dashboard tab and the wrist widget | LGPL-3.0 (also offered under GPL-2.0/GPL-3.0 or a commercial license); installed with pip as separate libraries, not copied into this repository |

The app also uses openvr, numpy and opencv-python from the list above.
