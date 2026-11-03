# Calibrating your cameras

Calibration has two parts:

1. **Lens calibration**, once per camera. It works out how each lens bends the picture.
2. **Room calibration**. It places every camera in your SteamVR play space.

After that, a point seen by two or more cameras can be placed in 3D in SteamVR coordinates. You
also need to do the room calibration again whenever a camera is moved.

Commands are shown as the `.bat` files you double-click on Windows. Each one runs `python -m tools.<name>` from
this folder, which works anywhere. Every run writes a log to `logs/`. Results go to
`calibration/data/`. That folder is per-machine, so never commit it.

## What you need

- **Two or more USB webcams (UVC)**, mounted so they can't move. High in the room corners, angled
  down, works well. Every spot you care about should be seen by at least two cameras.
- **A printer, or a print shop.** You need two sheets: the lens board and the tracker marker.
- **Something rigid and flat** to glue the board onto, like foam board or thick card. A bent board
  ruins lens calibration.
- **For room calibration, SteamVR and one tracker or controller.** A Vive tracker is easiest to
  attach to the marker.

## 0. Set up and find your cameras

1. Run `setup.bat`. It needs Python 3.12. Use `setup.bat pose` to also install the optional pose
   model.
2. Choose the mode in `config.yaml` under `cameras`: `width`, `height`, `fps` and `fourcc`. Lens
   calibration is only valid for the size it was done at, so pick the size you'll actually use.
3. Run `probe_cameras.bat`. It lists which device ids open and which deliver that mode. Put those
   ids in `cameras.ids` and give each camera a name in `cameras.names` (e.g. by wall: `north`,
   `east`, ...).
4. Run `preview.bat` to see every camera with its fps and brightness, and check which name is
   which. On Windows, `backend: dshow` usually reaches the highest frame rates, and `p` opens the
   driver's settings dialog.
5. Optional but recommended: set a fixed `exposure_ms` and `white_balance_k`, so brightness and
   colour don't change between cameras or over time. Flickering stripes in the preview mean the
   exposure is fighting your room lights. Try a longer exposure, or different lights.

Device ids can change when other cameras are plugged in, such as a laptop webcam or a headset's
passthrough camera. With `require_exact_mode: true`, a device that can't give your exact mode is
refused rather than used by mistake. Run `probe_cameras` again if a camera stops opening.

## 1. Print the board and the marker

Run `make_boards.bat`. It writes these files to `calibration/data/boards/`:

- `board_small.pdf`: the ChArUco board for lens calibration.
- `tracker_marker.pdf`: one large ArUco marker for room calibration.

Print both **at 100% / "Actual size", never "Fit to page"**, on matte paper if you can (gloss
reflects lights). Then:

- Measure the 100 mm ruler line printed on each sheet. Also measure one board square from edge
  to edge. If the square isn't exactly `square_mm` in `config.yaml` (34 mm by default), put your
  measured value in `calibration.boards.small.square_mm`, and scale `marker_mm` by the same
  factor.
- Glue the board flat onto your rigid sheet.
- Glue the marker onto stiff card. Fix the tracker **rigidly** to the card, sticking up past the
  card's top edge, so the card never covers the tracker's sensors. The tracker must not wobble
  relative to the marker. The marker can be anywhere on the card: its exact offset from the
  tracker is solved for.

For A4 paper, set `page_mm: [210.0, 297.0]` before running `make_boards`.

## 2. Lens calibration (once per camera)

Run `calib_intrinsics.bat cam1`, using a camera name or number. Then repeat it for every camera.

A window shows the camera with a grid over it. Hold the board in front of the camera, about 30 to
90 cm away, and:

- Move it slowly through the **whole picture**, including the corners and edges. The edges matter
  most, because that's where the lens bends the most.
- Bring it near and far, and tilt it left, right, up and down by about 30 to 45 degrees.
- **Pause** at each pose. A view is captured when the board is still and different enough from
  earlier views (the window flashes). Grid cells turn green once corners have been seen there.

It calibrates by itself after 40 views. Press `c` to calibrate early, space to force a capture, or
`q` to quit. Both a fisheye and a standard (rational) lens model are tried, and the better one is
kept.

**What good looks like:** the log ends with `GOOD`, which means:

- **Reprojection error (RMS) at or under 0.8 px.** Typical webcams reach 0.2 to 0.5 px. This is
  how far, on average, the detected board corners are from where the fitted lens model puts them.
- **Coverage at or over 60%** of the 8x6 grid. 80% or more is better, because the model is only
  trustworthy where it has seen the board.

If it says `REDO`, capture more views near the edges and corners, use more light, and check that
the board is flat.

The captured frames are kept, so you can recalibrate without the camera:
`calib_intrinsics.bat cam1 --from-dir`.

A lens calibration stays valid until you change the resolution, the focus, or the lens itself.
Moving the camera doesn't affect it.

## 3. Room calibration

First check:

- Every camera has its lens calibrated.
- The cameras are mounted in their final spots.
- SteamVR is running, and the tracker on the marker card is on and tracking.

Run `calib_room.bat`. A window shows every camera, with a counter on each one.

1. Walk slowly around the whole room holding the card so the marker faces the cameras. Use
   different heights, from the floor to above your head, and cover the space you'll actually use.
2. **Stop for about a second at each spot.** Only moments when the tracker is still are kept,
   because camera timing jitters a little.
3. **Tilt the card forward or back by 20 to 30 degrees at about every third stop.** If the tracker
   only ever turns flat (for example, on a tripod head that only pans), the camera heights can be
   off by the distance between the marker and the tracker. The log warns you if that happens.
4. A stop counts for every camera that sees it, so about 35 to 40 stops fill the default target of
   25 per camera. When every counter reaches its target, it solves by itself. You can also press
   `c` to solve early, or `q` to quit.

**What good looks like:**

- **RMS at or under 3 px per camera.** That's how far, on average, the tracker's SteamVR position,
  projected into the camera, lands from where the camera saw the marker. Good setups reach 1 to
  2 px.
- **Camera positions that make sense.** Each camera's position in metres is printed in SteamVR
  standing space, with y up and the floor at about y = 0. Check that the heights and distances
  between cameras roughly match what you'd measure with a tape.

The result is `calibration/data/room.json`. The run also saves one reference picture per camera,
which drift_check uses later. The raw observations are kept, so `calib_room.bat --resolve` solves
again without walking around.

## 4. Check it

Run `calib_check.bat` with SteamVR up and the marked tracker on. Each camera shows a **red ring**
where SteamVR says the marker is, and a **green ring** where the camera sees it. Move around the
room: the rings should sit on top of each other everywhere.

When you quit (`q`), the log prints a median gap in pixels per camera. A few pixels is good.
Anything much bigger than the room calibration's RMS means something has moved, or a
calibration is off.

## Later: did a camera move?

`drift_check.bat` compares each camera's view with the reference picture saved by the room
calibration. It reports any camera that has shifted by more than `calibration.drift.max_shift_px`.

- **A camera moved:** run the room calibration again. Its lens calibration is still fine.
- **"Unsure":** something big changed in front of that camera. Clear the view and run the check
  again.

## Good to know

- **SteamVR's standing space can move after calibration.** It moves when you rerun Room Setup,
  when you use playspace tools, and sometimes after tracking loss (one setup measured a 30 cm
  shift within days). The calibration describes standing space as it was on calibration day. If
  things line up worse over time, run calib_check. Then either do the room calibration again, or
  measure the shift live from the headset, as `fusion/align.py` does.
- **The `rotate` setting is only for display.** Calibration always uses raw, unrotated frames.
- Already have calibration from another tool? See [FORMATS.md](FORMATS.md).
