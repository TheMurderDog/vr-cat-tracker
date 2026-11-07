# VR cat tracker

## ⬇️ Download

[![Download the cat tracker (ZIP)](https://img.shields.io/badge/Download-Cat%20tracker%20(ZIP)-2ea44f?style=for-the-badge&logo=github)](https://github.com/TheMurderDog/vr-cat-tracker/archive/refs/heads/main.zip)
&nbsp;
[![Download the VRChat avatar package](https://img.shields.io/badge/Download-VRChat%20avatar%20package-1f6feb?style=for-the-badge&logo=unity)](https://github.com/TheMurderDog/vr-cat-tracker/raw/main/6_optional_vrchat/1_import_into_unity/CatTracker.unitypackage)

- **Cat tracker (ZIP):** the whole project. Unzip it anywhere, then open `0_start_here`. Check
  [What you need](#what-you-need) first: you'll print two sheets and need a SteamVR tracker or controller.
- **VRChat avatar package (optional):** `CatTracker.unitypackage`, to show your pet to friends in VRChat. See
  [6_optional_vrchat](6_optional_vrchat/README.md).

No GitHub account needed. Both buttons download straight away and give you the current version.

My cat kept surprising me while I was in VR, so I built this to see roughly where it is while I play. It uses
the cameras from my DIY full-body tracking setup to find it and show it in SteamVR. It's an extra hint, not a
guard: I still keep my play area clear and play carefully when the cat is in the room.

It shows a cat icon where the cameras think it is, with a ring on the floor under it. When it sees the cat close
to you, it shows a small arrow at the edge of your view pointing toward it, and buzzes the controllers. Its icon also
shows when it's asleep or running. It works in any SteamVR game, and moving or turning your play space doesn't move
its marker. Optionally it sends its position to VRChat over OSC, so friends can see it as an avatar prop.

> **Use at your own risk.** This is a hobby project, not a safety device. It can miss your pet, and it comes with no
> warranty: the authors aren't liable for any harm or damage. Whether and how you use it is up to you. Please read
> [DISCLAIMER.md](0_start_here/DISCLAIMER.md) before using it.

## Start here

**The folders are the instructions.** Open [`0_start_here`](0_start_here/README.md), then go through the numbered
folders in order. Each one has a README that says what the step does, what you need first, which scripts to run (they
are numbered in the order you run them), how you know you're done, and where to go next. Double-click a `.bat` file
to run it; each one tells you the next step when it finishes.

| Folder | What you do there |
| --- | --- |
| [`0_start_here`](0_start_here/README.md) | read what you need, install once |
| [`1_connect_cameras`](1_connect_cameras/README.md) | find your cameras and give each one a name |
| [`2_calibrate_cameras`](2_calibrate_cameras/README.md) | print a board, calibrate each lens, place the cameras in your SteamVR room |
| [`3_first_test`](3_first_test/README.md) | get the stock model and check it can find your cat, no headset needed |
| [`4_teach_it_your_cat`](4_teach_it_your_cat/README.md) | capture, label and train it on your own cat: the biggest improvement you can make |
| [`5_play_in_vr`](5_play_in_vr/README.md) | the finish line: see your cat in the headset |
| [`6_optional_vrchat`](6_optional_vrchat/README.md) | optional: friends in VRChat see your cat as a prop on your avatar |
| [`7_if_something_moved`](7_if_something_moved/README.md) | come back here if a camera got bumped or the base stations moved |
| `settings` | the two files you edit: `cameras.yaml` and `cat_tracker.yaml` |
| [`my_data`](my_data/README.md) | everything made on your PC (calibration, anchor, captures, models, logs), kept out of git |
| [`docs`](docs/README.md) | how it works, security, licenses, and technical details for developers |
| [`engine`](engine/README.md) | all the code. You never need to open it to set up the tracker. |

## What you need

- **Two or more USB webcams (UVC)**, mounted high and fixed in place, so every spot you care about is seen by at least
  two. More cameras give better results. Fixed focus, a manual focus ring, or autofocus that can be switched off:
  autofocus that can't be switched off will cause tracking problems.
- **Windows 10/11, an NVIDIA GPU, Python 3.12**, and about 6 GB of free disk space.
- **SteamVR** with your headset, plus a **tracker or controller** to fix to Board B (the marker card) for the room calibration.
- **Two printed sheets**, included in `0_start_here/print_these` (US Letter or A4): Board A, a checkerboard to glue
  onto something rigid like foam board, and Board B, a marker card to glue onto stiff card.
- **Bright, flicker-free light** (strongly recommended). Dim or flickering light hasn't been fully tested, and it makes everything harder, labelling
  most of all. Some LED and fluorescent bulbs flicker on camera; the camera setup in step 1 tries to point that out.
- **Your cat at home** for about 20 minutes, to teach the tracker what it looks like.

## Reference setup

This is the setup it was built and tested on. It was put together for full-body tracking, so it is more than a cat
tracker needs:

- **Cameras:** four BL29 USB colour cameras, one on each wall, mounted near the ceiling (about 2.5 m up) and
  angled down. They run 1280x720 at up to 120 fps for body tracking. The cat tracker uses 30 fps and a 7.8 ms
  exposure.
- **Lighting:** two flicker-free LED strips on the ceiling.
- **Tracking:** SteamVR with base stations.

With this setup, after training on the cat: all four cameras see it most of the time, nearly every position is
triangulated from two or more cameras, the anchor lines up with SteamVR to about 2 cm, and the detector keeps
GPU use mostly under 20%.

**Smaller setups haven't been tested.** You need at least two cameras: the cat's position is worked out where two
cameras see it. Where only one camera sees it for a moment, the tracker guesses a spot on the floor under its box,
which is rougher. Ordinary room lighting hasn't been fully tested either: it needs more exposure, and a light that
flickers at the exposure time shows as stripes. Try what you have and decide what is good enough.
Settings to tweak are mainly `cameras.exposure_ms`, `detector.gamma` and `detector.score` in
`settings/cat_tracker.yaml`, plus training on footage from your own cameras.

## Experimental parts

These are new and have only been tried on one setup (one room, one cat, one PC). They may change, and their numbers
come from that setup, so yours will differ:

- **TRAIN A HELPER** in step 4's `2_label.bat`: a quick model that suggests boxes for the pictures you haven't decided.
  Its suggestions can box empty pictures, so check each one. It needs the training environment from
  `3_first_test_get_stock_model.bat`.
- **NO CAT** in step 4's `1_capture.bat`: saves pictures as "no cat" while the cat is out of the room.
- **The light check** while the tracker runs, and the dim-room notice in `1_capture.bat`.
- **The CHECKS OK, A BIT DARK lines** in step 1's camera setup (darkness and grain judged together, the sharpness and
  flicker checks): measured, but tuned on one room.
- **The motion tripwire**, which tries to react faster when a sleeping cat suddenly runs. Its reaction time is an
  estimate added up from measured parts, not an end-to-end test.
- Already marked before: the focus lock (`k`) and `cameras.fps: auto`.

## How this was made

This project was built with heavy use of AI. Most of the code and documentation was written by Claude, an AI
model made by Anthropic, working in conversation with me (TheMurderDog):

- **Claude** wrote the code: detection, triangulation, the SteamVR overlay and anchor, the capture, autolabel,
  labelling and training tools, the alerts, the VRChat OSC sender. Claude also wrote the docs, including this README.
  It also proposed the overall approach and diagnosed problems from logs, such as the stuck white balance.
- **I** came up with the idea and made the design calls, for example tying everything to SteamVR's raw space
  because I move my play space a lot, replacing the beep with an edge-of-view arrow, and capping the hard-frame
  saving. I suggested the cross-camera and gap-filling autolabel. I built and calibrated the camera rig, captured
  and labelled the training data, and tested every change on real hardware with my cat.
- The **camera code** in `engine` was taken from my full-body tracking project, which was also built with Claude.

It has been tested on the reference setup above. If you'd rather not use AI-written software, this should help you
decide.

## License

Copyright (C) 2026 TheMurderDog. AGPL-3.0, because it uses Ultralytics YOLO11, which is AGPL-3.0. See
[LICENSE](LICENSE). The VRChat avatar files in `6_optional_vrchat/1_import_into_unity` are MIT licensed (see
[their LICENSE](6_optional_vrchat/1_import_into_unity/LICENSE)).

Developers and AI assistants: see [docs\technical](docs/technical/README.md).
