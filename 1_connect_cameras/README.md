# 1. Connect the cameras

Pick your cameras, name them, turn them upright and check them, on one screen.

## Before you start

- Step 0 done.
- Cameras plugged in and mounted where they will stay.
- Nothing else using the cameras: close the old tracker, fbt, video calls and camera apps.

## Run this

### `1_set_up_cameras.bat`

The first time, it opens on **ALL CAMERAS ON THIS PC** (every camera it finds, live) with none in use. Click your
room cameras one by one to use them (the order you click is the order they're used; click again to stop using one).
Not sure which picture is which camera? **Cover one with your hand**: its picture lights up. Press **N** on a camera
to name it: click **North**, **East**, **South** or **West** (the wall it's on), or type a name. **DONE** (or Esc) goes
to the main window, which shows only the cameras you use; **+ ADD / REMOVE CAMERAS** (or `c`) opens the list again.

| Do this | Key |
| --- | --- |
| Use a camera (or stop using it) | click it in the list (or select it and press space) |
| See it big, to aim it | click it in the main window. **< BACK** (or Esc) goes back |
| Give it a name | `n`, then click a wall name, or type one and press Enter |
| Move it earlier or later in the order | `[` and `]` in the list |
| Turn it upright | `r` (a quarter turn each press) |
| Leave it out, so it's never opened again (`x` on it again brings it back, where it was) | `x`, twice |
| This is a camera that wasn't found (moved to another USB port) | `a` in the list |
| Open the camera's own driver settings | `p` |
| Test the camera's other modes (when its picture quality isn't good) | `m`, then `y` to use the suggestion |
| Full screen on or off (the normal window can be moved and resized) | `f` |
| Save | `s` |
| Quit | `q` |

The main window shows the cameras you use, laid out as the tracker shows them: just their names, and a word
for each. Leave it running for a minute: each camera is **CHECKING** (yellow) while it's watched, so a brief thing like
someone walking past doesn't count. Then it's **FOCUS?** (yellow) until you click it and use **START FOCUS ASSIST**
(or **SKIP** if its picture is already sharp enough; remembered next time), and finally **CHECKS OK** (green): the
picture checks passed. In a dim room with a grainy picture it says **CHECKS OK, A BIT DARK** (yellow) instead: it can
be used and nothing is blocked, but more light helps it see the cat. (EXPERIMENTAL: the dark and grain lines were tuned
on one setup so far.) A problem that lasts gives a red frame
and **Click to resolve issues**: its big view says what's wrong and what to do. The yellow
**? HELP** button (or `?`) explains it all. The checks keep running while the screen is open, and a camera you
unplug shows **NOT CONNECTED**, then starts **CHECKING** again when it's back. When the line under the cameras
says all cameras passed the picture checks, press `s`.

In the big view, turn the camera itself until the floor fills the lower two thirds of the picture and standing
heads show in the top third (the brighter guide line, "heads above, floor below"). Tab (or
1-9) shows the next camera, `g` hides the guide lines.

**Focus.** Each camera says **FOCUS?** until it's done. If its picture is already sharp enough, its big view offers
**SKIP** (`O`); otherwise (or to be sure) use the focus assist:

1. Stand **Board B** (the marker card from step 0) upright on the floor in the middle of where your cat walks,
   facing the camera. Not near the camera: it should be sharpest where the cat will be. SteamVR isn't needed.
2. Open that camera big (click it again) and press **START FOCUS ASSIST** (or `C`). A green box appears around Board B: only the box is measured, so
   moving around elsewhere in the picture doesn't matter.
3. Stand beside the camera, out of its view. Turn the focus ring slowly all the way one way, then back. Soft ticks
   get faster as it gets sharper (`v` turns them off).
4. Stop when the circle is green and you hear **"That's in focus."** Good enough is fine: the rest of the room is
   a little softer anyway. Went wrong? Just turn it again (or press `b`).
5. If you changed the focus, redo that camera's lens step (step 2).

Without Board B it measures the whole picture: point the camera at something with detail, like a shelf.

**Autofocus cameras (experimental).** This hasn't been tried on a real autofocus camera yet. If the camera's driver
says the computer can set its focus, its big view shows `K` (auto-focus lock). Stand Board B where your cat walks,
stay out of the picture and press `K`. It switches autofocus off, steps the focus to find the sharpest point on
Board B, and locks it there (`-` and `+` nudge it). Every tool keeps it locked from then on. Then redo that
camera's lens step (step 2). If the picture doesn't change, it says the focus is the camera's ring, and `K`
isn't shown for that camera again (many focus-ring cameras claim autofocus). A camera whose autofocus can't be switched off is shown in red:
it will cause tracking problems, so use a different camera if you can. Tried it? Please say how it went in the
project's GitHub issues (github.com/TheMurderDog/vr-cat-tracker/issues), with the setup screen's log from
`my_data\logs\cameras`.

Cameras that can't be used are grey, with the reason written on them.

VR headset cameras (like the Valve Index's, called `eTronVideo`) and virtual cameras are excluded already: they
show as EXCLUDED and are never opened. To use one anyway, select it and press `x`.

**Aim your cameras while this is open.** Each one's live picture shows what it can see:

- Lower two thirds floor, top third for standing heads: the cat tracker lines itself up with SteamVR by seeing
  your head, so standing in the middle of the room, your head should show in at least two cameras.
- Keep bright lights and windows out of view, or near the edge.
- Every spot your cat walks should be seen by at least two cameras.
- If your room has furniture the cat hides behind, try to have its favourite spots seen by 3 cameras; it keeps
  its position steady when one camera's view is blocked.
- Fix the cameras firmly once they're aimed. Moving one after step 2 means calibrating again.

Not enough cameras to see every spot twice? Add another camera, then run this again.

## You're done when

Every camera you use says **CHECKS OK** (or **CHECKS OK, A BIT DARK**, though more light is better), and you've
saved. (Many cameras show about 120 fps at this size even when 30 is
asked for: that's their own speed, and fine.)

## If something's wrong

- **A camera is missing:** check its cable, try another USB port, close other camera programs, then run
  `1_set_up_cameras.bat` again. Still missing? Run `troubleshoot_find_cameras.bat`.
- **A camera came unplugged, or wasn't plugged in when you started a step?** Plug it in (any port): it joins by
  itself within a few seconds, in this screen, the calibration steps and the tracker. Meanwhile its picture says so.
- **Moved a camera to a different USB port?** Run `1_set_up_cameras.bat` and press `s`. It recognises the moved
  camera and keeps its name and calibration. Moved several at once? It lists them as not found: select each new
  picture, press `a` until it's the right camera, then `s`.
- **FLICKER:** your lights flicker. Set a fixed `exposure_ms` under `cameras` in `settings\cameras.yaml` (try `7.8`),
  or use different lights. To try exposures live, run `troubleshoot_preview_cameras.bat` and press `[` and `]`.
- **Damaged frames** (blocky or smeared patches that flicker, mostly in the lower part of the picture): that camera
  is short of USB bandwidth, usually because it shares a USB hub or controller with another camera. Plug it
  straight into a USB port on a different controller (for example the back of the PC), not into a hub. The
  damaged frames are dropped, so nothing uses them.
- **"Some" or "HEAVY compression":** the camera squeezes its pictures hard. If damaged frames are up too, move it
  to another USB port first. Otherwise press `m` to test its other modes; `y` uses the cleanest for every camera
  (if you've calibrated already, that calibration is put aside and step 2 has to be done again).
- **TOO SLOW, or dropped frames:** try another USB port (cameras sharing one USB hub can slow each other down).
- **Renamed or reordered cameras after step 2?** That's fine: each camera keeps its calibration.
- **Added a camera, or re-aimed one, after step 2?** Redo step 2: the lens step for a new camera, and the room
  calibration (a new walk) after any re-aiming. After saving, the setup screen says what's missing.

## Next

Open [2_calibrate_cameras](../2_calibrate_cameras/README.md).

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
