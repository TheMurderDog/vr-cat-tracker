# 2. Calibrate the cameras

Teach the tracker how each lens bends the picture, and where each camera is in your room.

This is the longest part of setup, and you only do it once. You'd only come back if a camera moves or you turn a
focus ring (see [7_if_something_moved](../7_if_something_moved/README.md)).

## Before you start

- [ ] Step 1 done, with the cameras in their final spots.
- [ ] Board A and Board B from [0_start_here/print_these](../0_start_here/print_these/README.md), printed and mounted.
- [ ] **Board A** (the checkerboard) for script 1, and **Board B** (the marker card) for scripts 2 and 3.
- [ ] SteamVR running, with the tracker or controller on Board B switched on (for scripts 2 and 3).

## Run these in order

### 1. `1_lens_calibration.bat`

**Turn your speakers on.** It goes through your cameras one by one, full screen, and talks you through each one.

1. Hold the **board** 30 to 90 cm from that camera. Move it toward the **lit-up box**, following the arrow and the
   voice ("Move left", "Higher", "Tilt the board": Board A). Left and right are yours, as you face the camera. The beeps get faster as you get close.
2. **Pause** at each spot.

If moving Board A feels backwards, press **M** to mirror the picture.

When every area is covered and it has enough views, it finishes that camera by itself and moves on to the next.
Each should end with **FIT GOOD**. A chime means it took a view.

### 2. `2_room_calibration.bat`

Start SteamVR first, with the tracker or hand controller on Board B switched on. It must be fixed firmly to the
back of Board B, behind the dashed area, sticking up past the top edge, so it can't wobble and doesn't cover the
marker.

1. When asked, **wave Board B**. That's how it knows which tracker or controller to follow (next time it
   remembers).
2. Walk slowly around the room holding **Board B** facing the cameras, low and high.
3. **Stop for about a second** at each spot. A chime means the stop counted.
4. Every third stop or so, **tilt Board B** forward or back a little.

The camera with the yellow frame needs stops most. About 35 to 40 stops fill every counter, and then it finishes by
itself. Each camera should say **FIT GOOD**.

If a camera isn't FIT GOOD yet, you don't start over: the FIT GOOD ones are kept, and it tells you what that camera needs
(for example "closer to it, and farther away"). Keep walking for it. If more stops don't help, it stops asking and
finishes. **FIT OK** means a little less precise but fine to use. For a camera that's FIT OK or FIT NOT GOOD, it says what to
check, for example: wipe its lens, and check it's in focus and firmly mounted.

Your stops are saved as you go. If you quit or it closes, run it again and it continues where you left off (press `r`
to start over instead). Your previous room calibration is kept in `my_data\backups`.

### 3. `3_check_calibration.bat`

Move Board B around the room, stopping now and then. Each camera shows a **red ring** (where SteamVR says
the marker is) and a **green ring** (where the camera sees it). They should sit on top of each other everywhere.
Each camera says **FIT GOOD** once it has seen enough. `q` finishes and shows the result.

## You're done when

Every camera says FIT GOOD in the check.

## If something's wrong

- **CHECK YOUR PRINT:** the printer stretched Board A. Measure it (17.0 cm wide, 23.8 cm tall), print it again
  on another printer, and redo the lens calibration.
- **REDO on a lens:** run `1_lens_calibration.bat` again (press `s` to skip the FIT GOOD ones). More light helps, and
  check the board is flat.
- **No voice:** check your speakers. `v` turns it on and off.
- **"The cat tracker is using the cameras":** you set the tracker to start with SteamVR, so it took the cameras.
  Press `s` in that window (or run `5_play_in_vr\stop_tracker.bat`), and calibration starts by itself.
- **"Waiting for SteamVR to see your base stations and tracker":** SteamVR is still starting. Check the base stations
  are on and the tracker's light is green; it goes on by itself.
- **Stopped a camera halfway?** Its views are kept. Next time, press Enter at that camera to finish with them.
- **Room calibration says FIT NOT GOOD, or camera heights look wrong:** walk it again, with more varied and tilted stops.
- **A camera's counter stops climbing:** walk where that camera can see Board B. If nothing changes for a minute, it
  offers to finish with what it has.
- **"Your controller turned off":** controllers switch off when they aren't moved for a while. Switch it back on;
  it carries on by itself.
- **A camera says OFF in the check:** run `2_room_calibration.bat` again. If one camera is still off, redo its lens.
- **You renamed or reordered cameras in step 1 afterwards:** nothing to redo. Re-aimed a camera? Redo
  `2_room_calibration.bat` with a new walk (its lens is still fine, unless you changed its focus or zoom).
- More detail: [docs/CALIBRATION.md](../docs/CALIBRATION.md).

## Next

Open [3_first_test](../3_first_test/README.md).

## Your notes

<!-- Make sure the user knows this is a one time process because this is the worst part of setting this up. Don't want them to think they have to do this all the time. -->
