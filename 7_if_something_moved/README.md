# 7. If something moved

Come back here if a camera got bumped, or the tracker asks you to re-anchor.

## Before you start

- [ ] Nothing big standing in front of the cameras.
- [ ] The tracker stopped: `5_play_in_vr\stop_tracker.bat` (it holds the cameras). Start it again afterwards with
      `6_optional_vrchat\restart_with_vrchat.bat` or `5_play_in_vr\restart_tracker.bat`, or by restarting SteamVR.

## Run these in order

1. `drift_check.bat` - tells you if any camera moved, and how much that matters.
   - **MOVED:** run `2_calibrate_cameras\2_room_calibration.bat` and `3_check_calibration.bat` again. Its lens
     calibration is still fine.
   - **"Moved a little":** fine, nothing to do (it says how far off that puts the cat: about 1 cm is nothing).
   - **"Unsure":** clear the view in front of that camera and run the check again.
2. **Redo the anchor:** run `5_play_in_vr\run_tracker.bat` and press the **REDO ANCHOR WALK** button (or `a`). Clear
   the floor first, then put the headset on and walk slowly around the room, only where you know it's clear. It
   waits for you and stops by itself.

## You're done when

No camera is reported as moved, and the re-anchor notice is gone.

## Good to know

- **Base stations moved, or SteamVR reset its tracking:** usually nothing to do. The tracker fixes the anchor
  itself while you play, and only asks if it can't.
- **Running SteamVR's Room Setup again:** nothing to do.
- **A camera plugged into another USB port:** nothing to do. Each camera is recognised by its own USB ID.
- **A camera refocused, or its lens changed:** its lens calibration is out of date. Run
  `2_calibrate_cameras\1_lens_calibration.bat` for that camera (Board A), then the room calibration and the check.

## Next

Back to [5_play_in_vr](../5_play_in_vr/README.md).

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
