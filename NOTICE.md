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
| PyYAML | config.yaml | MIT |
| openvr (pyopenvr) | tracker poses from SteamVR | BSD-3-Clause (Valve's OpenVR SDK it wraps: BSD-3-Clause) |
| *optional* onnxruntime-gpu | running the pose model | MIT (its CUDA/cuDNN pip packages are under NVIDIA's own license terms) |
| *optional* rtmlib | pose model wrapper | Apache-2.0 |

## Pose model (`pose/baseline.py`), used by the cat tracker's anchor

`pose/baseline.py` uses two pretrained models from OpenMMLab's MMPose project, through rtmlib:

- **RTMPose-m**, trained on seven public pose datasets ("body7"), with Halpe 26 keypoints.
- **YOLOX-m**, a person detector trained on Human-Art.

The URLs are in `config.yaml` under `pose`.

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

Everything else in this folder works without the pose model: capture, both calibrations,
triangulation and filtering. Leave out `requirements-pose.txt` and don't call `pose.baseline`.
`fusion/align.py` reads only the keypoint names from `pose/baseline.py`, not the models.

## Cat tracker (`cat_tracker/`)

Also written for this project; no code copied from elsewhere. Extra dependencies:

| Package | Used for | License |
| --- | --- | --- |
| ultralytics (YOLO11) | training the cat detector (`train.bat`, its own environment) | AGPL-3.0 |
| torch, torchvision | training | BSD-3-Clause |
| onnx, onnxslim, onnxconverter-common | exporting the trained model | Apache-2.0 / MIT |
| onnxruntime-gpu | running the detector | MIT |

The YOLO11 model weights (`yolo11s.pt`, downloaded by Ultralytics) are AGPL-3.0. No model files are included.
