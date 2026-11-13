# VRChat avatar: cat stand-in

This shows a stand-in cat on your VRChat avatar at the spot where the cat tracker sees your real cat. You can see it in VR, and so can everyone else in the instance. The tracker sends the cat's position, state and heading over OSC. This drop-in prefab turns those values into a cat on the floor that:

- shows when the cat is seen and hides when it isn't,
- stands at the right distance and side from your head (it doesn't follow your head tilt or your eyes),
- sits as high off the floor as the cameras see the cat (on a sofa or a bed, for example), when two or more cameras see it,
- locks in place in the world while you stand still, so it doesn't swim when you look around, and follows again when you move,
- optionally (experimental) holds still in the world while your thumbsticks rest, even while you walk around your room for real ([Play-space anchor](#play-space-anchor-experimental)),
- faces the way the cat is heading once the tracker knows it, and faces you until then,
- switches between four poses: **Standing**, **Sleeping**, **Walking** and **Alert** (alert shows while the tracker is warning you that the cat is close),
- tries to stand on top of the world's floor and furniture when the cat lands slightly inside them, and shows a small glowing hover pad under the cat when its real height is above the world's floor ([Floor and hover pad](#floor-and-hover-pad)),
- can be hidden from the Action menu (**Cat Tracker > Cat**).

The package ships with a simple placeholder cat (a low-poly stick figure). Swap in your own model as described below.

## Requirements

- Unity 2022.3 (the version VRChat currently uses) with the **VRChat Avatars SDK 3.10.x** (tested with 3.10.5; the play-space anchor, floor check and hover pad with 3.10.6, which has the VRC Raycast component they use)
- **VRCFury** (tested with 1.1433.0; the play-space anchor with 1.1442.0), installed through the VRChat Creator Companion
- The cat tracker from this repository running on the same PC, with OSC enabled in VRChat (Action menu > Options > OSC > Enabled)

## What's in the package

`CatTracker.unitypackage` (in `6_optional_vrchat/1_import_into_unity`) imports one folder, `Assets/CatTracker/`:

| Path | What it is |
|---|---|
| `Cat Tracker.prefab` | The drop-in prefab |
| `System/` | Tracker logic: FX controller, expression parameters, animation clips |
| `Model/` | Placeholder cat: FBX, two plain materials (VRChat Mobile Toon Lit), pose clips, the pose controller |
| `Hover Pad/` | The hover pad: disc mesh, its shader (`CatTracker/Hover Pad`) and material, and its two clips (`Hover Pad On`, `Hover Pad Off`) |
| `Editor/CatTrackerViewPoint.cs` | Small build-time script (see below) |

`6_optional_vrchat/1_import_into_unity/blender/` has the placeholder's `.blend` file, its FBX, and `build_cat_placeholder.py`, the script that generates it.

**About the Editor script:** `CatTrackerViewPoint.cs` runs every time the avatar is built (Play mode or upload), just before VRCFury. It reads the avatar descriptor's view position and moves the prefab's `CatHeadRef` there, inside the build copy only. It doesn't save anything, read or write files, or use the network. As with any `.unitypackage`, read it before you import. If you leave it out, the head point falls back to a typical eye offset of 6 cm up and 8 cm forward from the head bone.

## Setup

1. Import `CatTracker.unitypackage` into your avatar project (VRChat SDK and VRCFury already installed).
2. Drag `Cat Tracker.prefab` onto your avatar's root object in the Hierarchy (directly under the object with the Avatar Descriptor). Leave its position, rotation and scale at zero, zero and one.
3. That's it. VRCFury adds the FX layers, parameters and a **Cat Tracker** submenu (with the **Cat** toggle) when you enter Play mode or upload. You don't need to edit your FX controller, menu or parameter list.
4. Check the avatar's synced parameter budget: the prefab adds **53 bits**.
5. If you're updating from an older version of the package, use Reset Config in VRChat's OSC menu after uploading, so VRChat picks up the new parameters.

How it fits on your avatar: VRCFury's **Armature Link** snaps `CatHeadLink` onto your avatar's Head bone (position only), and `CatHeadRef` inside it sits at your view position. Everything else stays under the prefab.

## Parameters (OSC)

These match the names, types and units sent by the tracker's `osc.py`. All of them arrive at `/avatar/parameters/<name>`.

| Parameter | Type | Synced | Meaning |
|---|---|---|---|
| `CatAhead` | Float -1..1 | yes | Metres ahead of the headset (its facing, ignoring tilt) ÷ `range_m` |
| `CatRight` | Float -1..1 | yes | Metres to the headset's right ÷ `range_m` |
| `CatUp` | Float 0..1 | yes | Metres from the floor up to the cat's feet ÷ `range_m` (0 when only one camera sees it) |
| `CatVisible` | Bool | yes | The cat is seen, or was seen recently |
| `CatState` | Int | yes | 0 normal (Standing), 1 resting (Sleeping), 2 moving (Walking) |
| `CatNear` | Bool | yes | The tracker is warning that the cat is close (Alert pose) |
| `HeadRoomYaw` | Float -1..1 | yes | Headset heading on the room floor, degrees ÷ 180, clockwise from above |
| `CatRoomYaw` | Float -1..1 | yes | Cat heading, same units and frame as `HeadRoomYaw` |
| `CatHeadingKnown` | Bool | yes | The cat has moved enough to know its heading |
| `CatAnchorMode` | Bool | yes | Play-space anchor on: `CatAhead` and `CatRight` are measured from the anchor, not the headset (experimental, off unless turned on in the tracker settings) |

`CatShow` (Bool, synced, saved, default on) is the **Cat** toggle in the menu. The tracker doesn't send it. When it's off, the cat stays hidden whatever the tracker sends.

The prefab also uses local parameters that it drives itself: `CatInRange` and `CatAnchored`, and the raycast outputs `CatFloor_Hit`, `CatFloor_Ratio`, `CatGround_Hit` and `CatGround_Distance`. It also reads VRChat's built-in `VelocityMagnitude` and `AngularY`. The tracker also sends `CatRoomX`, `CatRoomZ`, `HeadRoomX` and `HeadRoomZ`. The prefab doesn't use them, and VRChat ignores parameters an avatar doesn't have.

## Play-space anchor (experimental)

Without it, the cat's position is measured from your headset each update, and the prefab locks it in the world only while you stand still. With it, the tracker fixes a reference point in your room while you're not moving yourself with the controllers, and measures the cat from that point instead. The avatar freezes that point in the VRChat world, so the stand-in cat tries to stay put while you look around or walk around your room for real. It's only as good as the tracker's view of your cat and SteamVR tracking (see the limits below and [Known limits](#known-limits)).

To turn it on, set `vrchat.stick_anchor.enabled: true` in `settings/cat_tracker.yaml` (see [settings_reference.md](technical/settings_reference.md)), then restart SteamVR so it loads the tracker's controller bindings. Only turn it on with a version of this prefab that has `CatAnchorMode`: an older prefab would draw the cat from your head while the tracker measures from the anchor, so the cat would land in the wrong spot.

How it decides:

- **Head mode** (the cat is measured from your headset, as without the anchor) while you push a thumbstick, press a button other than the grip or a trackpad (A/B/X/Y, trigger, menu), or move SteamVR's play space more than 3 cm or 1° (for example with OVR Advanced Settings).
- **Anchored** about a second after you let go, once your head is steady for half a second. There's no time limit: if your head doesn't settle, it stays in head mode.
- It reads the controllers through SteamVR Input without taking them over, so VRChat still gets every input. If the controllers can't be read for a second, it goes back to head mode.

Limits:

- VRChat teleports, seats, moving platforms and other movement that doesn't come from your sticks or buttons can't be seen by the tracker, so the cat can sit in the wrong spot until your next stick push or button press.
- Someone who joins the instance while you're anchored sees the cat measured from your head until your next stick push or button press.
- It was tested by the author on one avatar with an Index headset and controllers. Other controllers use the bindings in `engine/cat_tracker/input/` and haven't been tried.

## Floor and hover pad

The cameras and the VRChat world don't share a floor, so the stand-in cat can end up inside a world's floor or furniture, or floating above it. Two VRC Raycasts (`HitWorlds` only, so they ignore players) try to help:

- **Floor check.** `CatRoot/CatOffset/CatFloorRay` looks 0.5 m down from 0.5 m above the cat's tracked spot. If it hits the world, the cat is lifted onto that surface (FX layer **Cat Floor**, 0.15 s blend). So a world surface up to 0.5 m above the tracked spot lifts the cat onto it, and one that's higher is ignored.
- **Hover pad.** `CatSmoothed/CatFloorHit/CatGroundRay` measures from the cat down to the world, up to 3 m. When the gap is more than 10 cm, or there's no world surface within 3 m, the FX layer **Cat Hover** fades in the pad under the cat (0.3 s, with a 1 cm bob). It fades out below 6 cm, or when the cat hides.

Both are local: each player's VRChat client runs the raycasts against its own copy of the world, so no synced bits are used.

**Swap the pad for your own.** The pad's parts are kept apart from the tracker logic so you can replace them:

- *Different look, same behaviour:* delete `CatSmoothed/CatMesh/Hover Pad/Pad Visual` and put your own object inside `Hover Pad`, with its centre at the cat's feet. The **Cat Hover** layer scales `Hover Pad` from almost zero to full size and back, so anything inside it fades in with it. The `material._Fade` curve in the two clips then has nothing to animate, which Unity ignores. Or keep the disc and only change the material's colours, strength and pulse speed.
- *Different behaviour:* the clips are `Hover Pad/Hover Pad On.anim` (looping) and `Hover Pad Off.anim`, used by the **Cat Hover** layer in `System/Cat Tracker FX.controller`. Edit them, or point the layer's two states at your own clips. The layer's conditions use `CatVisible`, `CatGround_Hit` and `CatGround_Distance` (metres), which you can also use in your own layers.
- *No pad:* delete the `Hover Pad` object. The **Cat Hover** layer then animates nothing.
- *No floor check either:* also delete `CatFloorRay`, `CatFloorHit` and `CatGroundHit`, and remove the **Cat Floor** and **Cat Hover** layers from the FX controller.

## Distance scale (calibration)

The prefab assumes the tracker's default `range_m: 4.0`, an avatar at scale 1, and a 1 m offset showing as 1 m. If the cat shows up too close or too far:

1. Start SteamVR and VRChat (OSC on) and close the real tracker so the two don't both send.
2. Run `6_optional_vrchat\2_osc_test.bat`. It places a pretend cat 1 m straight ahead of you and shows a ring on the floor at that spot in SteamVR. Press **2** to move it to 2 m and **1** to move it back. Press **u** to lift it 0.5 m, then 1 m, then back to the floor, to check the height.
3. If the stand-in cat sits short of or past the ring, change the scale of `Cat Tracker/CatRoot` in Unity by the same ratio (ring at 1 m, cat at 0.8 m → multiply by 1.25). Then set `Cat Tracker/CatSmoothed` to 1 divided by that number, so the cat itself keeps its size. Re-upload and check again at both 1 m and 2 m.
4. If you change `range_m` in `settings/cat_tracker.yaml`, multiply the `CatRoot` scale by `new range_m ÷ 4`, and set `CatSmoothed` to 1 divided by the new `CatRoot` scale, as in step 3.

## Use your own model

The cat model lives in `Cat Tracker/CatSmoothed/CatMesh/Model`. Its pivot is the cat's spot on the floor and +Z is the cat's forward direction. Choose one of these two ways:

**A. Keep the pose controller (animated or rigged model).**
1. Delete or disable `Model/Placeholder` and put your model inside `Model`, with its feet at the pivot, facing +Z, at real-world size.
2. Make one clip per state (Standing, Sleeping, Walking, Alert) that animates your model. Paths are relative to the `Model` object. The `Cat_*.anim` clips in `Model/Animations` show the format.
3. Open `Model/Cat Model FX.controller`. In the **Cat Pose** layer, put your clips into the four states.

**B. One object per state (no animation needed).**
1. Delete or disable `Model/Placeholder`.
2. Put a separate object (a posed mesh, a sprite, anything) inside each of `Model/Standing`, `Model/Sleeping`, `Model/Walking` and `Model/Alert`. The **Cat Pose Slots** layer turns on only the slot that matches the current state.
3. Optionally, clear the clips from the **Cat Pose** layer states so nothing animates the old placeholder paths.

Keep materials light: this is a prop that other players render too.

## Performance cost (placeholder)

| Item | Count |
|---|---|
| Skinned meshes | 1 (784 triangles, 16 bones) |
| Meshes | 1 (hover pad, 192 triangles) |
| Material slots | 3 (2 placeholder, 1 hover pad) |
| Raycasts | 2 (floor check and hover pad) |
| PhysBones | 1 (2 transforms, no colliders), used to smooth movement |
| Contacts | 2 (1 sender, 1 receiver), used for the world lock |
| Constraints | 7, plus whatever your own model brings |
| FX layers | 11 (9 tracker, 2 pose); all states have Write Defaults off |
| Synced parameter bits | 53 |

## Known limits

- **First-person head shrink:** in your own first-person view, VRChat shrinks your head bone, and the head point (a child of the head) shrinks with it. So in your own view the cat can land short of where other players see it. On the avatar this was built for, the gap was large enough to need a 1.26x larger `CatRoot` scale. There are two ways to handle it:
  - Calibrate in first person with `6_optional_vrchat\2_osc_test.bat` as described above. You'll see the cat in the right place, but other players may see it a little too far away.
  - Add a VRChat **VRC Head Chop** component that targets `CatHeadRef` with scale factor 1, which keeps the point at your eyes in your own view. This isn't included and hasn't been tested with this prefab, because Head Chop only works inside VRChat.
- The position is only as good as the tracker's camera calibration and SteamVR tracking. If the room calibration drifts, the cat drifts with it.
- If you scale your avatar in game, the distance scales with it. Calibrate at the avatar scale you normally use.
- Remote players see the cat with normal network latency and smoothing. Fast movement looks smoother but slightly late.
- Heading is blended from 22.5° steps and sent as an 8-bit float (about 1.4° per step), so facing is close but not exact.
- **Floor check and hover pad** only see world colliders. Worlds without colliders on a surface, or with invisible ones, can put the cat on or above the wrong surface. The cat isn't pushed out of walls or furniture from the side. A surface up to 0.5 m above the tracked spot (a table edge or a low shelf) can lift the cat onto it. Height changes from one surface to the next aren't smoothed, so on steps the cat jumps up or down.
- When the wearer looks straight up or down, the tracker can't measure "ahead", so the cat hides for that moment.
- **Height** comes from the cameras' 3D estimate of the cat's middle, minus a typical body height (`locate.body_height_m`, 15 cm), and counts as the floor below 10 cm (`vrchat.height_snap_m`). With only one camera on the cat, it's placed on the floor. A box whose floor point lands outside the room (a cat high up near a wall, seen from across the room) is dropped, the same check that drops pictures on the wall. The height is roughly where the cameras think the cat is, and uses the same distance scale as `CatRoot` (see [Distance scale](#distance-scale-calibration)).

## License

The contents of `6_optional_vrchat/1_import_into_unity/` are MIT licensed (see [LICENSE](../6_optional_vrchat/1_import_into_unity/LICENSE)). The rest of the repository (the tracker) is AGPL-3.0.
