# 6. VRChat (optional)

Let friends in VRChat see a stand-in cat on your avatar, where your real cat is.

## Before you start

- [ ] Step 5 working.
- [ ] Unity 2022.3 with the **VRChat Avatars SDK** and **VRCFury** (from the VRChat Creator Companion).
- [ ] In VRChat, OSC on: Action Menu, Options, OSC, Enabled. (Changed your avatar's parameters? Use Reset Config
      in that same menu.)

## Run these in order

1. **Add the prop to your avatar**, in Unity:
   - Import `1_import_into_unity\CatTracker.unitypackage` into your avatar project. It has one small Editor script,
     `CatTrackerViewPoint.cs`, which only moves the prop's head point to your avatar's view when you build or upload.
     It reads and writes no files and uses no network.
   - Drag `Cat Tracker.prefab` onto your avatar's root object (the one with the Avatar Descriptor). Leave its position,
     rotation and scale at 0, 0 and 1.
   - Upload the avatar. It uses 52 bits of your synced parameters.
2. `2_osc_test.bat` - shows a pretend cat 1 m in front of you, and a ring on the floor in SteamVR. The stand-in cat
   should sit on the ring. Press `2` for 2 m, `1` for 1 m, `u` to lift it 0.5 m, then 1 m, then back to the floor,
   `q` to quit. Close the real tracker first.
3. `3_run_with_vrchat.bat` - runs the tracker and sends your cat to the avatar.
4. `4_install_autostart_vrchat.bat` (optional) - does that by itself every time SteamVR starts. Run it with SteamVR
   open. It replaces step 5's autostart if you installed that. Undo with
   `5_play_in_vr\start_with_steamvr\remove_autostart.bat`. If you installed the app
   ([5_play_in_vr](../5_play_in_vr/README.md#the-app-optional)), it starts with SteamVR too.

`restart_with_vrchat.bat` restarts it with no window, for example after changing a setting.

## You're done when

Friends see the stand-in cat where your cat is.

## If something's wrong

- **The stand-in cat sits short of or past the ring in step 2:** in Unity, scale `Cat Tracker/CatRoot` by ring
  distance ÷ cat distance (ring at 1 m, cat at 0.8 m: × 1.25). Set `Cat Tracker/CatSmoothed` to 1 ÷ that scale so the
  cat keeps its size. Upload and check at 1 m and 2 m.
- **Nothing shows in VRChat:** check OSC is on (and try Reset Config there), and that the tracker shows the cat in
  SteamVR.
- **The stand-in cat swims a little as you walk around your room:** try the experimental play-space anchor in
  [docs/vrchat_avatar.md](../docs/vrchat_avatar.md#play-space-anchor-experimental).
- Your own cat model, the parameters and known limits: [docs/vrchat_avatar.md](../docs/vrchat_avatar.md).

## Next

You're finished!

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
