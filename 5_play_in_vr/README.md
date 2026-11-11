# 5. Play in VR

See your cat in the headset: a cat icon where the cameras think it is, and an arrow and a buzz when it's close.

## Before you start

- [ ] Step 4 done.
- [ ] SteamVR running, headset on.
- [ ] Every other camera tool closed (the camera setup screen, the desktop test, `1_capture` and `2_label`): they
      hold the cameras.

## Run this

### `run_tracker.bat`

**The first time only:** clear the floor first (cables, bags, toys). Then put the headset on and walk slowly around
the room, only where you know it's clear. It waits until the headset is on your head and moving, says when to start,
and stops by itself when it has enough (usually 20 to 40 seconds). This lines the cameras up with your headset (the
**anchor**). It's saved, so you don't need to do it again unless a camera moves. A walk that didn't line up well isn't saved:
it says why, and you try again.

Window keys: `q` quits, `a` (or the **REDO ANCHOR WALK** button, top left) redoes the anchor. You can start it
before putting the headset on: the walk waits for you. With [the app](#the-app-optional) installed, the app opens
instead of that window: use its **Stop** and **Re-anchor** buttons.

## The app (optional)

A window, a tab in the SteamVR dashboard and a small widget on your wrist, so you can do most things from VR with
the laser pointer: start and stop the tracker, redo the anchor, see the cameras and a room map of where the cat
tends to be, change how the marker looks, and tune or snooze the warnings.

1. `app\1_install_app.bat` - once. It adds the app to the same install (a few hundred MB download).
2. `app\2_open_app.bat` - opens it. With SteamVR running, open the dashboard and pick the cat tab.

Once it's installed, the app opens by itself however the tracker starts: `run_tracker.bat`,
`6_optional_vrchat\3_run_with_vrchat.bat`, the restart scripts and the SteamVR autostart. The warnings are an extra
hint, not a promise: keep the floor clear and look before you step.

**Foot trackers (optional):** with SteamVR trackers on your feet, the distance and the warnings use whichever is
closest to the cat, either foot or your headset. To assign them, sit down, press **Assign foot trackers** (VR tab:
Alerts; desktop: Alerts & widget) and wave each foot when asked.

## You're done when

You see the cat icon on your real cat in the headset.

## Make it start by itself (optional)

- `start_with_steamvr\install_autostart.bat` - the tracker starts with SteamVR every time, with no window. Run it
  with SteamVR open, after `run_tracker.bat` has saved an anchor once. Using VRChat? Install
  `6_optional_vrchat\4_install_autostart_vrchat.bat` instead (it replaces this one; there's only ever one).
- `start_with_steamvr\remove_autostart.bat` - undoes that.
- `stop_tracker.bat` - closes the tracker when it has no window. Closing SteamVR closes it too.
- `restart_tracker.bat` - restarts it with no window, for example after changing a setting.

## If something's wrong

- **A notice asks you to re-anchor:** press `a` in the tracker window and walk around again, or see
  [7_if_something_moved](../7_if_something_moved/README.md).
- **Red "CAT TRACKER STOPPED" in VR:** it crashed. Run `restart_tracker.bat` or `run_tracker.bat`, or
  `stop_tracker.bat` to hide the notice.
- **The icon sits a little off your cat:** measure from the front of your headset to the middle of your head, and
  set it in `settings\cameras.yaml` under `fusion` (right, up, back, in metres), then redo the anchor (`a`). For 8 cm
  back and 2 cm down: `headset_to_head_m: [0.0, -0.02, 0.08]`
- **The PC crashes or freezes while you play:** see [If your PC crashes](#if-your-pc-crashes) just below.
- How it all works: [docs/how_it_works.md](../docs/how_it_works.md).

### If your PC crashes

Some graphics drivers crash or freeze the whole PC (a blue screen, or a black screen and a restart) when several
programs use the graphics card at once during VR. These steps helped on one PC. Try them in order, one at a time, so
you can tell which one does it for yours:

1. **Picture mode.** In the app: Settings > Pictures in the VR tab, or Alerts & widget > SteamVR pictures on the
   desktop. The app then sends its VR pictures to SteamVR as files and uses no graphics card itself. It switches
   straight away. If the PC went down while the app was open, the app offers this on its next start.
2. **Move other programs to the built-in graphics,** if your PC has them (many Intel and AMD processors do). Windows
   Settings > System > Display > Graphics: add the program (your browser, chat apps), open its options and choose
   Power saving. For an app from the Microsoft Store, pick "Microsoft Store app" in the list first. Leave SteamVR,
   your VR game and the tracker as they are. To undo, set the program back to "Let Windows decide".
3. **Reinstall the graphics driver cleanly.** Install your graphics card maker's current driver with its "clean
   installation" option, or try the version before it. This changes your system: follow the driver maker's
   instructions.

## Try this

- **Kneel or sit down next to your cat.** The icon should stay on it, not drift as your head moves.
- **Let it walk toward you.** The tracker is set to show the arrow at the edge of your view and buzz when it sees the
  cat within 1 m, within 1.8 m and moving, or heading your way fast enough to meet within 2.5 s. Those are
  `underfoot_m`, `radius_m` and `ttc_s` under `alert` in `settings\cat_tracker.yaml`.
- **Watch the icon while it sits or sleeps.** It should stay still. If it jitters (for example with the tail out),
  note where in your notes below.

## Next

For friends in VRChat to see your cat: [6_optional_vrchat](../6_optional_vrchat/README.md). Otherwise, you're
finished! If a camera gets bumped later: [7_if_something_moved](../7_if_something_moved/README.md).

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
