# Calibrating your cameras

Calibration has two parts:

1. **Lens calibration**, once per camera. It works out how each lens bends the picture.
2. **Room calibration**. It places every camera in your SteamVR play space.

After that, a point seen by two or more cameras can be placed in 3D in SteamVR coordinates. You
also need to do the room calibration again whenever a camera is moved.

Commands are shown as the `.bat` files you double-click on Windows, in the numbered step folders. Each one runs
`python -m tools.<name>` from `engine`. Every run writes a log to `my_data/logs/cameras`. Results go to
`my_data/calibration/`. That folder is per-machine, so never commit it.

## What you need

- **Two or more USB webcams (UVC)**, mounted so they can't move. High in the room corners, angled
  down so the floor fills the lower two thirds of the picture and standing heads the top third, works well.
  Every spot you care about should be seen by at least two cameras, and so should your head when you stand in
  the middle of the room (the cat tracker lines itself up with SteamVR by seeing it). Fixed focus, a manual
  focus ring, or autofocus that can be switched off: autofocus that can't be switched off will cause tracking problems.
- **A printer, or a print shop.** You need two sheets: **Board A** (the checkerboard, for lens calibration) and **Board B** (the marker card,
  for room calibration and checking focus). The tools and the voice call them that.
- **Something rigid and flat** to glue Board A onto, like foam board or thick card. A bent board
  ruins lens calibration.
- **For room calibration, SteamVR and one tracker or controller.** A Vive tracker is easiest to
  attach to Board B.

## 0. Set up and find your cameras

1. Run `0_start_here\1_install.bat`. It needs Python 3.12. It also installs the pose model the cat
   tracker's anchor uses.
2. Choose the mode in `settings/cameras.yaml` under `cameras`: `width`, `height`, `fps` and `fourcc`. Lens
   calibration is only valid for the size it was done at, so pick the size you'll actually use.
3. Run `1_connect_cameras\1_set_up_cameras.bat`. It shows every camera that opens, live, and you pick the ones to use,
   name them, order them and turn them upright on screen; `s` saves them to `cameras.ids`, `cameras.names` and
   `cameras.rotate`. (`1_connect_cameras\troubleshoot_find_cameras.bat` lists the ids as text instead.) Put those
   ids in `cameras.ids` and give each camera a name in `cameras.names` (e.g. by wall: `north`,
   `east`, ...).
4. The setup screen also shows every camera's fps, dropped frames, flicker and brightness. For a longer check,
   or to try exposures with `[` and `]`, run `1_connect_cameras\troubleshoot_preview_cameras.bat`. Check which name is
   which. On Windows, `backend: dshow` usually reaches the highest frame rates, and `p` opens the
   driver's settings dialog.
5. Optional but recommended: set a fixed `exposure_ms` and `white_balance_k`, so brightness and
   colour don't change between cameras or over time. Flickering stripes in the preview mean the
   exposure is fighting your room lights. Try a longer exposure, or different lights.
6. Cameras with a focus ring: stand Board B on the floor where your cat walks, facing the camera, open the camera
   big in the setup screen and turn the ring slowly all the way one way, then back, until it says "That's in
   focus." Only Board B's area is measured. Good enough is fine. Do this before lens calibration.

Device ids can change when other cameras are plugged in, such as a laptop webcam or a headset's
passthrough camera. With `require_exact_mode: true`, a device that can't give your exact mode is
refused rather than used by mistake. Run `1_connect_cameras\1_set_up_cameras.bat` again if a camera stops opening.

## 1. Print Board A and Board B

Ready-made sheets for the default settings are in `0_start_here/print_these` (US Letter and A4):

- Board A (`board_A_checkerboard.pdf`), the ChArUco checkerboard, for lens calibration.
- Board B (`board_B_marker_card.pdf`), one large ArUco marker, for room calibration and checking focus.
  Printed them before they had names? Write A and B on them.

Need other sizes? See [technical/custom_boards.md](technical/custom_boards.md).

Print both **at 100% / "Actual size"**, on matte paper if you can (gloss reflects lights). Then:

- Measure Board A: 17.0 cm wide and 23.8 cm tall (the default board). A little smaller both ways is fine.
  If only one of them is off by more than 2 mm, the printer stretched it: print it again on another printer.
  Board B needs no measuring.

Only one thing about the print matters: the board must not be stretched one way more than the other. Its
overall size doesn't matter (a lens calibration comes out the same from a board printed a few percent small, so
"Fit to page" is harmless), and neither does Board B's size (only its centre is used). But a printer that
stretches the paper one way by even 1% makes the lens model several pixels wrong across the picture, and the
wizard can't tell, because the board then fits its own wrong shape. Measured in simulation through a real lens:
3% or 6% smaller changed nothing; a 1% one-way stretch gave about 12 px of error at the edges of the picture,
3% about 40 px.

The lens wizard checks for this itself: it fits the board's height/width along with the lens. A stretch of 0.5% or
more (`calibration.intrinsics.stretch_correct_above`) is corrected for ("Your printout is slightly stretched. I've
corrected for it."), and 3% or more (`stretch_reprint_above`) says CHECK YOUR PRINT instead of FIT GOOD. Even shrinks
are ignored. Each lens result saves the stretch it found (`board_stretch`, `stretch_corrected`).
- Glue the board flat onto your rigid sheet.
- Glue Board B onto stiff card. Fix the tracker, or a hand controller, **rigidly** to the back of the card,
  behind the dashed area printed above the marker, sticking up past the card's top edge, so the card never covers its sensors. Any position and angle works: the
  room calibration measures where the marker sits relative to it (tested up to about 30 cm away, turned any way).
  A controller works as well as a tracker, so you don't need full-body trackers. It must not wobble
  relative to the marker. The marker can be anywhere on Board B: its exact offset from the
  tracker is solved for.

## 2. Lens calibration (once per camera)

Run `2_calibrate_cameras\1_lens_calibration.bat`. It goes through every camera in turn, fullscreen, lights up the
next area to cover with an arrow to it, and says which way to move ("Move left", "Higher", "Tilt the board"), with
beeps that speed up as you get there. Each camera starts capturing straight away; `s` skips one, and one that's already FIT GOOD is skipped by itself
(`r` redoes it). `m`
mirrors the picture, if moving the board feels backwards (off by default; display only), `f` toggles fullscreen, `v` the voice. For one camera only:
`1_lens_calibration.bat --cam cam1`.

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

**What good looks like:** the log ends with `FIT GOOD`, which means:

- **Reprojection error (RMS) at or under 0.8 px.** Typical webcams reach 0.2 to 0.5 px. This is
  how far, on average, the detected board corners are from where the fitted lens model puts them.
- **Coverage at or over 60%** of the 8x6 grid. 80% or more is better, because the model is only
  trustworthy where it has seen the board.

If it says `REDO`, capture more views near the edges and corners, use more light, and check that
the board is flat.

The captured frames are kept, so you can recalibrate without the camera:
`2_calibrate_cameras\1_lens_calibration.bat --cam cam1 --from-dir`.

A lens calibration stays valid until you change the resolution, the focus, or the lens itself.
Moving the camera doesn't affect it.

## 3. Room calibration

First check:

- Every camera has its lens calibrated.
- The cameras are mounted in their final spots.
- SteamVR is running, and the tracker (or controller) on Board B is on and tracking.

Run `2_calibrate_cameras\2_room_calibration.bat`. First it asks you to **wave Board B**: whichever tracker or
controller moves the most is the one it follows. It remembers it for next time and for the check step. Then a window
shows every camera, with a counter on each one; the camera with a yellow frame needs stops most.

1. Walk slowly around the whole room holding Board B so the marker faces the cameras. Use
   different heights, from the floor to above your head, and cover the space you'll actually use.
2. **Stop for about a second at each spot.** Only moments when the tracker is still are kept,
   because camera timing jitters a little. A chime means the stop counted.
3. **Tilt Board B forward or back by 20 to 30 degrees at about every third stop.** If the tracker
   only ever turns flat (for example, on a tripod head that only pans), the camera heights can be
   off by the distance between the marker and the tracker. The log warns you if that happens.
4. A stop counts for every camera that sees it, so about 35 to 40 stops fill the default target of
   25 per camera. When every counter reaches its target, it solves by itself. You can also press
   `c` to solve early, or `q` (it asks whether to solve with the stops you have). If no camera gains a stop
   for a minute and each has at least 12, it offers to finish after a 10-second countdown; another stop
   cancels it.

If a camera isn't FIT GOOD after solving, the run doesn't end. The FIT GOOD cameras are kept and marked done (never asked
again), and you walk again for the others: the screen and the voice say what each one needs (more stops, the card
nearer the edges of its view, closer to it and farther away, low and high, or tilted toward it), and it asks 10 more
stops of it, then solves again by itself. That happens at most `retry_rounds` times (2), and only while the camera's
error keeps dropping: an error that more stops don't shrink comes from the camera or the card, not from the walk.
Then it finishes and says so: a camera up to `ok_px` (4.5 px) is **FIT OK** (a little less precise, fine to use), above
it **FIT NOT GOOD**, with what to check: many stops thrown out means the device on Board B wobbles; a lens result that
is itself poor means redo that camera's lens step; a picture much softer than the other cameras' means wipe its
lens and check focus and mounting (if you change its focus, redo its lens step and the walk). A lens that passed its
own step is almost never the cause: checked on the test setup's cameras, each lens predicted views it wasn't fitted on to
about 0.2 px everywhere in the picture, while room errors are around 1-4 px. Your stops are saved as you walk, so if you quit (or it crashes), the next run offers to
continue them (`r` starts over).

The result screen says FIT GOOD, FIT OK or FIT NOT GOOD per camera, out loud too. Your previous room calibration is copied to
`my_data\backups` first.

**What good looks like:**

- **RMS at or under 3 px per camera.** That's how far, on average, the tracker's SteamVR position,
  projected into the camera, lands from where the camera saw the marker. Good setups reach 1 to
  2 px.
- **Camera positions that make sense.** Each camera's position in metres is printed in SteamVR
  standing space, with y up and the floor at about y = 0. Check that the heights and distances
  between cameras roughly match what you'd measure with a tape.

The result is `my_data/calibration/room.json`. The run also saves one reference picture per camera,
which `7_if_something_moved\drift_check.bat` uses later. The raw observations are kept, so `2_calibrate_cameras\2_room_calibration.bat --resolve` solves
again without walking around.

## 4. Check it

Run `2_calibrate_cameras\3_check_calibration.bat` with SteamVR up and Board B's tracker or controller on. It
follows the same device as the room calibration (or asks you to wave it). Each camera shows a **red ring**
where SteamVR says the marker is, and a **green ring** where the camera sees it. Move around the
room, stopping now and then: the rings should sit on top of each other everywhere.

Each camera's counter shows the median gap in pixels, and once it has seen enough it says **FIT GOOD** (at most
`check_max_px`, 6 px by default) or **OFF**, out loud too. When you quit (`q`), a summary per camera is shown and
spoken, and written to the log. OFF means something has moved, or a calibration is off.

## Later: did a camera move?

`7_if_something_moved\drift_check.bat` compares each camera's view with the reference picture saved by the room
calibration. It reports any camera that has shifted by more than `calibration.drift.max_shift_px`.

- **A camera moved:** run the room calibration again. Its lens calibration is still fine.
- **"Unsure":** something big changed in front of that camera. Clear the view and run the check
  again.

## Good to know

- **SteamVR's standing space can move after calibration.** It moves when you rerun Room Setup,
  when you use playspace tools, and sometimes after tracking loss (one setup measured a 30 cm
  shift within days). The calibration describes standing space as it was on calibration day. If
  things line up worse over time, run `2_calibrate_cameras\3_check_calibration.bat`. Then either do the room calibration again, or
  measure the shift live from the headset, as `engine/fusion/align.py` does (the cat tracker's anchor does this for you).
- **The `rotate` setting is only for display.** Calibration always uses raw, unrotated frames.
- Already have calibration from another tool? See [technical/FORMATS.md](technical/FORMATS.md).
