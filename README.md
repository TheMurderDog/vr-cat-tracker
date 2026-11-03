# VR cat tracker

My cat kept surprising me while I was in VR, and sometimes I'd step on her or bump into her, so I ended up
shutting her out of the room when I played. This project uses the cameras from my DIY full-body tracking
setup to find her and show her in SteamVR, so now she can hang out with me while I play.

It shows a cat icon floating where she really is, with a ring on the floor under her. When she's close, a small
arrow appears at the edge of your view pointing toward her, and the controllers give a short buzz. That
happens whenever she's under 1 m away, within 1.8 m if she's moving, and earlier when one of you is closing in
fast. A napping cat a little way off doesn't set it off. Her icon also shows when she's asleep (still for
2 minutes) or running. It works in any SteamVR game, and moving or turning your play space doesn't move her
marker. Optionally it sends her position to VRChat over OSC, so friends can see her as an avatar prop.

> **Use at your own risk.** This is a hobby project, not a safety device. It can miss your pet, and it comes with no
> warranty: the authors aren't liable for any harm or damage. Making your setup safe enough is up to you. Please read
> [DISCLAIMER.md](DISCLAIMER.md) before using it.

Most of this project was written by an AI (Claude). See [How this was made](#how-this-was-made) for who did what.
[docs/build_guide.md](docs/build_guide.md) explains how it was built step by step, including the decisions,
the mistakes and what we learned. It's written so you can paste it into your own Claude project and build one for
your setup.

## What's in this repo

| Folder | What it is |
| --- | --- |
| the top level (`core/`, `capture/`, `calibration/`, `fusion/`, `pose/`, `tools/`) | the **camera core**: multi-webcam capture and calibration for SteamVR, taken from my full-body tracking project. It places ordinary USB webcams in your SteamVR space, so anything two or more cameras see can be located in 3D. See [CORE_README.md](CORE_README.md) and [CALIBRATION.md](CALIBRATION.md). |
| `cat_tracker/` | the cat tracker, built on top of the camera core |
| `docs/build_guide.md` | how it was built, for pasting into your own Claude project |

## What you need

- **Two or more USB webcams (UVC)**, mounted high and fixed in place, so every spot you care about is seen by at least two.
- **SteamVR**, plus a tracker or controller for the room calibration.
- **An NVIDIA GPU** for the detector and the optional pose model. Windows 10/11, Python 3.12.
- A printer for the calibration board and marker.

## Reference setup

This is the setup it was built and tested on. It was put together for full-body tracking, so it is more than a cat
tracker needs:

- **Cameras:** four BL29 USB colour cameras, one on each wall, mounted near the ceiling (about 2.5 m up) and
  angled down. They run 1280x720 at up to 120 fps for body tracking. The cat tracker uses 30 fps and a 7.8 ms
  exposure.
- **Lighting:** two flicker-free LED strips on the ceiling.
- **Tracking:** SteamVR with base stations.

With this setup, after training on the cat: all four cameras see her most of the time, nearly every position is
triangulated from two or more cameras, the anchor lines up with SteamVR to about 2 cm, and the detector keeps
GPU use mostly under 20%.

**Less should work too.** Two cameras is the minimum for triangulation, and one camera still gives a floor
position. Ordinary room lighting can work, but it needs more exposure, and a light that flickers at the exposure time
shows as stripes. This hasn't been tested with smaller setups, so try what you have and decide what is good enough.
Settings to tweak are mainly `cameras.exposure_ms`, `detector.gamma` and `detector.score` in
`cat_tracker/config.yaml`, plus training on footage from your own cameras.

## Getting started

1. **Set up and calibrate the cameras:** run `setup.bat pose`, then follow [CALIBRATION.md](CALIBRATION.md) (find
   the cameras, lens calibration for each, room calibration, check). The pose model is what the cat tracker uses to
   line the cameras up with SteamVR from your head.
2. **Check she's found:** `cat_tracker\desktop_test.bat`, with no VR needed. It starts with the stock YOLO model
   (get it as described in [cat_tracker/models/README.md](cat_tracker/models/README.md)), which will miss her a lot.
3. **Train it on your cat. This isn't optional if you want it to work well.** The stock model has never seen a cat
   from a ceiling camera. Follow [cat_tracker/TRAINING.md](cat_tracker/TRAINING.md): capture, autolabel, label, train.
   One round took my tracker from about 1 camera in 4 seeing her to all 4.
4. **In VR:** start SteamVR, then `cat_tracker\run.bat`. The first time, put the headset on and walk slowly around
   the room for 10 to 20 seconds (the anchor).

Settings are in `config.yaml` (the cameras) and `cat_tracker/config.yaml` (the cat tracker). In the top-level
`config.yaml`, check `fusion.headset_to_head_m` (from the headset to the middle of your head): the default suits a
typical headset, so measure yours for the best anchor.

All of the cat tracker's scripts below are in `cat_tracker\` and are run from there.

## Use

| Script | What it does |
| --- | --- |
| `run.bat` | The tracker. Start SteamVR first. On first run it asks you to put the headset on and walk slowly around the room for about 10 to 20 seconds (the anchor, below). Add `--reuse-anchor` to skip that next time. |
| `desktop_test.bat` | Same detection with no SteamVR: the four cameras with her box drawn, and her position in the window. Good for checking she's found before going into VR. |
| `capture.bat` | Saves one frame from each camera every 2 s for training, with the stock model's guesses as starting labels, into `cat_tracker\captures`. Leave it running while she wanders, plays and naps (10 minutes is 1200 images). `c` in any tracker window starts and stops capturing too. |
| `autolabel.bat` | Run before `label.bat`. Where one camera found her, it projects her outline into the cameras that missed her; where she was found before and after a gap in the same spot, it fills the gap. Added boxes show orange in `label.bat` for you to check. |
| `label.bat` | Goes through the newest capture: drag a box around her, right-click a wrong box to delete it, `z` to undo, `r` to reuse the previous frame's box (shown blue), space for next, `x` for "no cat here". You can stop and carry on later. |
| `train.bat` | Fine-tunes the model on every checked image in `captures`, in its own environment (`cat_tracker\.venv`, created on first run, about 3.5 GB). Prints how well it does on held-out images and saves `models\cat_finetuned.onnx`, plus the two config lines that switch the tracker to it. |
| `install_autostart.bat` | Makes the tracker start with SteamVR, with no window, using the saved anchor (run `run.bat` once first). SteamVR must be running when you run it. Add `--osc` to send her to VRChat too. `install_autostart.bat --remove` undoes it, or switch it off in SteamVR's startup overlay apps. It closes when SteamVR does, or double-click `stop_tracker.bat` to close it sooner. |
| `train_more.bat` | Like `train.bat`, but starts from your last trained model and runs 20 epochs: quicker when you've added a capture session. |
| `check_recording.bat` | Runs the detector over a photo (`--image path`). Saves pictures of every frame she was found in to `cat_tracker\logs\snapshots`. |

While it runs, the tracker also saves moments the model struggled with (two or more cameras sure of her, another one that should see her missing her) into `captures\<date>-<time>-hard`, at most 150 moments per run and only with 10 GB free. `label.bat` goes through every session with unchecked images, newest first, so just run it, then `train_more.bat`. Skip `autolabel.bat` for these: their missing-camera boxes are already filled in (orange). Every 3 minutes it also checks the saved anchor against your head; if it's more than 10 cm off, a notice shows low in your view until you re-anchor.

If the tracker stops without being closed (a crash, or its console window closed), a red **CAT TRACKER STOPPED**
notice shows in VR and the controllers buzz. Restart it with `restart_tracker.bat` or `run.bat`, or run
`stop_tracker.bat` to hide the notice.

Window keys: `q` quits, `a` re-runs the anchor, `s` saves a snapshot, `c` starts/stops capturing. Logs go to `cat_tracker\logs`.

The cameras can only be opened by one program at a time, so close `preview.bat` (or anything else using them) first.

## How it works

1. **Detect.** YOLO11s (trained on COCO, which includes cats) runs on all four cameras in one GPU batch,
   5 times a second (the marker is still re-placed from your head 30 times a second). `models\yolo11s_fp16.onnx` stores its weights as fp16 to halve the file; the maths runs in fp32.
2. **Locate.** A box only counts if the floor under it is inside the room (the box around the four
   cameras), which throws out pictures on the walls, like the bear painting. Two or more cameras: her box centres are triangulated with the camera core's `Rig`. One camera:
   the bottom of her box is projected onto the floor. Anything above 1 m (`max_height_m`) is thrown out too. Then the camera core's jump gate and One Euro filter steady it.
   Weak detections (down to 0.08) also count, but only where she's expected: overlapping her outline as projected
   from another camera's sighting, or from where she just was. That cuts flicker and gets more cameras triangulating.
   She must be seen 3 detections in a row before she's shown, and when she disappears her marker dims and fades over 8 s.
3. **Anchor.** The room calibration is in SteamVR *standing* space as it was on calibration day, and standing
   space moves (one setup measured ~30 cm; play space tools move it all the time). The overlay is placed using
   SteamVR's *raw* space instead, which stays fixed to the base stations. To line the cameras up with raw
   space, the anchor runs the pose model for a few seconds and pairs your eyes and ears (seen by the
   cameras) with your headset's raw pose, the same idea as the core's `fusion\align.py`, but solving the
   room's turn as well as its offset. It's saved to `data\anchor.json`. Redo it (`a`) if the cameras or base stations move.
4. **Show.** Every update, raw space is converted to the current standing space, so her icon stays on the
   real cat however the play space has been dragged or turned.

Settings are in `cat_tracker\config.yaml`. Its `cameras` section overrides the top-level camera settings for the
cat tracker's own runs only, for example a longer fixed exposure (the reference setup uses 7.8 ms instead of the
3.9 ms its body tracking uses), because a cat needs brightness more than sharpness.

## Teaching the model your cat

The stock YOLO model learned from internet photos. It doesn't know your cat, lying down, under your ceiling cameras. Training on your own footage is the biggest single
improvement you can make: [cat_tracker/TRAINING.md](cat_tracker/TRAINING.md) walks through it step by step.

If you use a fixed white balance, the tracker toggles each camera's auto white balance at startup and sets the fixed
value again: two of my cameras had kept an old, much bluer white balance while still reporting the right one.

## Not done yet

- Showing her to friends in VRChat: `run.bat --osc` sends her position (see `osc.py`); the avatar side is being built separately.

## Safety: it's an aid, not a guarantee

This helps you notice your cat. It can't promise you'll never step on her, so please don't play as if it did.

- **It can miss her.** Before you've trained it on your cat, it misses her often. Afterwards it can still miss her
  when she's hidden from every camera, under furniture, in a blind spot, in poor light, or moving fast.
- **It lags a little.** It looks for her a few times a second, and a sprinting cat can be underfoot before the
  arrow shows.
- **It tells you when it stops working.** If a camera stops sending pictures or detection keeps failing, a notice
  shows in VR. If the tracker itself crashes, is closed or freezes, a small separate watchdog shows
  "CAT TRACKER STOPPED" in front of you and buzzes the controllers (`health` in `cat_tracker/config.yaml`). The
  watchdog can't help if your whole PC or SteamVR hangs, so still check that you see her marker when she walks in
  before trusting it in a session.
- **Keep your normal VR habits:** a cleared play area, SteamVR's boundary, and slower movements when she's around.
  Don't rely on it for small children or other pets it wasn't trained on.
- **If the cameras or base stations move,** the marker can be in the wrong place. The tracker checks this every few
  minutes and shows a notice; re-anchor when it does.

Full list of risks and your responsibilities: [DISCLAIMER.md](DISCLAIMER.md). As the license says, it comes with no
warranty and the authors aren't liable for damages.

## Privacy and security

It runs locally and opens no network ports. The VRChat option sends positions to `127.0.0.1` (this PC) only.

- **It saves pictures.** `capture.bat` saves camera frames, and while the tracker runs it also saves "hard" frames
  for training by itself (`hard_frames` in `cat_tracker/config.yaml`; set `enabled: false` to stop it). These are
  pictures of your room and anyone in it. If you live with other people, let them know the cameras are there and
  what gets saved.
- Captures, logs and calibration pictures are kept out of git. Be careful sharing them.
- Only load `.pt` model files you trust (they can run code).

See [SECURITY.md](SECURITY.md) for more.

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
- The **camera core** at the top level was taken from my full-body tracking project, which was also built with Claude.

It has been tested on the reference setup above. If you'd rather not use AI-written software, this should help you decide.

## License

AGPL-3.0, because it uses Ultralytics YOLO11, which is AGPL-3.0. See [LICENSE](LICENSE).
