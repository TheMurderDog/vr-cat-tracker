# How it works

1. **Detect.** YOLO11s (trained on COCO, which includes cats, then fine-tuned on yours in step 4) runs on all four
   cameras in one GPU batch, a few times a second: 8 times while the cat is moving or close to you, 3 while it's
   still or away (`detector.rate_hz` and `idle_rate_hz`). The marker is still re-placed from your head 30 times a
   second. The trained model stores its weights as fp16 to halve the file; the maths runs in fp32.
2. **Locate.** A box only counts if the floor under it is inside the room (the box around the cameras), which throws
   out pictures on the walls, like a painting. Two or more cameras: its box centres are triangulated with the camera
   code's `Rig`. One camera: the bottom of its box is projected onto the floor. Anything above 1 m (`max_height_m`) is
   thrown out too. Then the camera code's jump gate and One Euro filter steady it.
   Weak detections (down to 0.08) also count, but only where it's expected: overlapping its outline as projected
   from another camera's sighting, or from where it just was. That cuts flicker and gets more cameras triangulating.
   It must be seen 2 detections in a row before it's shown (`filter.confirm_frames`), and when it disappears its
   marker dims and fades over 8 s.
3. **Anchor.** The room calibration is in SteamVR *standing* space as it was on calibration day, and standing
   space moves (one setup measured ~30 cm; play space tools move it all the time). The overlay is placed using
   SteamVR's *raw* space instead, which stays fixed to the base stations. To line the cameras up with raw
   space, the anchor runs the pose model for a few seconds and pairs your eyes and ears (seen by the
   cameras) with your headset's raw pose, the same idea as `engine/fusion/align.py`, but solving the
   room's turn as well as its offset. It's done once, during setup, and saved to `my_data/tracker/anchor.json`.
   While you play, the tracker checks it every few minutes and corrects small slips by itself; it asks you to
   redo it (`a` in the tracker window) only when it can't, for example after a camera was bumped.
4. **Show.** Every update, raw space is converted to the current standing space, so its icon stays on the
   real cat however the play space has been dragged or turned.

Settings are in `settings/cat_tracker.yaml`. Its `cameras` section overrides `settings/cameras.yaml`'s camera
settings for the cat tracker's own runs only, for example a longer fixed exposure (the reference setup uses 7.8 ms
instead of the 3.9 ms its body tracking uses), because a cat needs brightness more than sharpness.

If you use a fixed white balance, the tracker toggles each camera's auto white balance at startup and sets the fixed
value again: two of my cameras had kept an old, much bluer white balance while still reporting the right one.

## Where things are

The step scripts in the numbered folders change into `engine` and run `python -m <package>.<module>` with the
Python in `.venv`. Training uses its own environment, `.venv-train`, so PyTorch never clashes with the camera code.
Every path in the settings files is relative to the top folder, and everything made on your PC goes in `my_data`
(see [its README](../my_data/README.md)).
