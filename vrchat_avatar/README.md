# VRChat avatar: cat stand-in

This shows a stand-in cat on your VRChat avatar at the spot where the cat tracker sees your real cat. You can see it in VR, and so can everyone else in the instance. The tracker sends the cat's position, state and heading over OSC. This drop-in prefab turns those values into a cat on the floor that:

- shows when the cat is seen and hides when it isn't,
- stands at the right distance and side from your head (flat on the floor, so it doesn't follow your head tilt or your eyes),
- locks in place in the world while you stand still, so it doesn't swim when you look around, and follows again when you move,
- faces the way the cat is heading once the tracker knows it, and faces you until then,
- switches between four poses: **Standing**, **Sleeping**, **Walking** and **Alert** (alert shows while the tracker is warning you that the cat is close).

The package ships with a simple placeholder cat (a low-poly stick figure). Swap in your own model as described below.

## Requirements

- Unity 2022.3 (the version VRChat currently uses) with the **VRChat Avatars SDK 3.10.x** (tested with 3.10.5)
- **VRCFury** (tested with 1.1433.0), installed through the VRChat Creator Companion
- The cat tracker from this repository running on the same PC, with OSC enabled in VRChat (Action menu > Options > OSC > Enabled)

## What's in the package

`CatTracker.unitypackage` imports one folder, `Assets/CatTracker/`:

| Path | What it is |
|---|---|
| `Cat Tracker.prefab` | The drop-in prefab |
| `System/` | Tracker logic: FX controller, expression parameters, animation clips |
| `Model/` | Placeholder cat: FBX, two plain materials (VRChat Mobile Toon Lit), pose clips, the pose controller |
| `Editor/CatTrackerViewPoint.cs` | Small build-time script (see below) |

`blender/` has the placeholder's `.blend` file, its FBX, and `build_cat_placeholder.py`, the script that generates it.

**About the Editor script:** `CatTrackerViewPoint.cs` runs every time the avatar is built (Play mode or upload), just before VRCFury. It reads the avatar descriptor's view position and moves the prefab's `CatHeadRef` there, inside the build copy only. It doesn't save anything, read or write files, or use the network. As with any `.unitypackage`, read it before you import. If you leave it out, the head point falls back to a typical eye offset of 6 cm up and 8 cm forward from the head bone.

## Setup

1. Import `CatTracker.unitypackage` into your avatar project (VRChat SDK and VRCFury already installed).
2. Drag `Cat Tracker.prefab` onto your avatar's root object in the Hierarchy (directly under the object with the Avatar Descriptor). Leave its position, rotation and scale at zero, zero and one.
3. That's it. VRCFury adds the FX layers and parameters when you enter Play mode or upload. You don't need to edit your FX controller, menu or parameter list.
4. Check the avatar's synced parameter budget: the prefab adds **43 bits**.

How it fits on your avatar: VRCFury's **Armature Link** snaps `CatHeadLink` onto your avatar's Head bone (position only), and `CatHeadRef` inside it sits at your view position. Everything else stays under the prefab.

## Parameters (OSC)

These match the names, types and units sent by the tracker's `osc.py`. All of them arrive at `/avatar/parameters/<name>`.

| Parameter | Type | Synced | Meaning |
|---|---|---|---|
| `CatAhead` | Float -1..1 | yes | Metres ahead of the headset (its facing, ignoring tilt) ÷ `range_m` |
| `CatRight` | Float -1..1 | yes | Metres to the headset's right ÷ `range_m` |
| `CatVisible` | Bool | yes | The cat is seen, or was seen recently |
| `CatState` | Int | yes | 0 normal (Standing), 1 resting (Sleeping), 2 moving (Walking) |
| `CatNear` | Bool | yes | The tracker is warning that the cat is close (Alert pose) |
| `HeadRoomYaw` | Float -1..1 | yes | Headset heading on the room floor, degrees ÷ 180, clockwise from above |
| `CatRoomYaw` | Float -1..1 | yes | Cat heading, same units and frame as `HeadRoomYaw` |
| `CatHeadingKnown` | Bool | yes | The cat has moved enough to know its heading |

The prefab also uses two local parameters that it drives itself, `CatInRange` and `CatAnchored`, plus VRChat's built-in `VelocityMagnitude` and `AngularY`. The tracker also sends `CatRoomX`, `CatRoomZ`, `HeadRoomX` and `HeadRoomZ`. The prefab doesn't use them, and VRChat ignores parameters an avatar doesn't have.

## Distance scale (calibration)

The prefab assumes the tracker's default `range_m: 4.0`, an avatar at scale 1, and a 1 m offset showing as 1 m. If the cat shows up too close or too far:

1. Start SteamVR and VRChat (OSC on) and close the real tracker so the two don't both send.
2. Run `osc_test.bat` from the tracker folder. It places a pretend cat 1 m straight ahead of you and shows a ring on the floor at that spot in SteamVR. Press **2** to move it to 2 m and **1** to move it back.
3. If the stand-in cat sits short of or past the ring, change the scale of `Cat Tracker/CatRoot` in Unity by the same ratio (ring at 1 m, cat at 0.8 m → multiply by 1.25). Then set `Cat Tracker/CatSmoothed` to 1 divided by that number, so the cat itself keeps its size. Re-upload and check again at both 1 m and 2 m.
4. If you change `range_m` in the tracker's `config.yaml`, multiply the `CatRoot` scale by `new range_m ÷ 4`, and set `CatSmoothed` to 1 divided by the new `CatRoot` scale, as in step 3.

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
| Material slots | 2 |
| PhysBones | 1 (2 transforms, no colliders), used to smooth movement |
| Contacts | 2 (1 sender, 1 receiver), used for the world lock |
| Constraints | 7, plus whatever your own model brings |
| FX layers | 8 (6 tracker, 2 pose); all states have Write Defaults off |
| Synced parameter bits | 43 |

## Known limits

- **First-person head shrink:** in your own first-person view, VRChat shrinks your head bone, and the head point (a child of the head) shrinks with it. So in your own view the cat can land short of where other players see it. On the avatar this was built for, the gap was large enough to need a 1.26x larger `CatRoot` scale. There are two ways to handle it:
  - Calibrate in first person with `osc_test.bat` as described above. You'll see the cat in the right place, but other players may see it a little too far away.
  - Add a VRChat **VRC Head Chop** component that targets `CatHeadRef` with scale factor 1, which keeps the point at your eyes in your own view. This isn't included and hasn't been tested with this prefab, because Head Chop only works inside VRChat.
- The position is only as good as the tracker's camera calibration and SteamVR tracking. If the room calibration drifts, the cat drifts with it.
- If you scale your avatar in game, the distance scales with it. Calibrate at the avatar scale you normally use.
- Remote players see the cat with normal network latency and smoothing. Fast movement looks smoother but slightly late.
- Heading is blended from 22.5° steps and sent as an 8-bit float (about 1.4° per step), so facing is close but not exact.
- When the wearer looks straight up or down, the tracker can't measure "ahead", so the cat hides for that moment.

## License

The contents of this `vrchat_avatar/` folder are MIT licensed (see [LICENSE](LICENSE)). The rest of the repository (the tracker) is AGPL-3.0.
