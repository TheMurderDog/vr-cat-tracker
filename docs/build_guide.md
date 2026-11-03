# Pet tracker for VR: how we built it

This is a write-up of how one person and Claude built a system that uses an existing multi-camera
room setup to track a cat and show it in VR, so it stops getting stepped on. It is written so you
can paste it into your own Claude project as a starting point and get to the same place much faster
than we did.

**How to use this file:** paste the whole thing into your Claude project (project instructions, or the
first message). Then fill in the "About my setup" section at the top of the prompt below. Everything
after the prompt is background: what we built, in what order, why, and what went wrong along the way.

**Safety note:** what's described here is a hobby project, not a safety device. It can miss your pet, and you build
and use it at your own risk. See [DISCLAIMER.md](../DISCLAIMER.md).

---

## The prompt (paste this, then fill in the blanks)

> I want to build a pet tracker for VR, following the guide below that a friend made with Claude.
> I already have a working multi-camera setup in my room. Please use the guide as the plan, but check
> my setup first and adapt anything that doesn't fit, rather than copying file names or numbers blindly.
>
> **About my setup** (fill in):
> - Cameras: how many, model, resolution/fps, colour or IR, where they are mounted:
> - Are they already calibrated (lens intrinsics + positions in one shared room frame)? Which software/format:
> - What tracking software already uses them, and can two programs open them at once:
> - Headset and tracking (Lighthouse base stations, inside-out, etc.):
> - GPU:
> - OS and Python version:
> - Do I use play space tools (OVR Advanced Settings, OpenVR Space Calibrator, etc.):
> - Pet(s): species, size, colour, favourite spots:
> - Do I want the pet visible to others in VRChat too, or only to me:
>
> **Rules for working with me:**
> - My existing camera/tracking project is off limits: read from it, import from it, but never modify it.
>   Put everything for this in its own folder (and its own Python environment for training).
> - Build the safety part first (a SteamVR overlay marker that works in every game). VRChat is a later, optional phase.
> - Give me .bat (or shell) scripts to double-click for every step, and tell me exactly what to run next.
> - When you change a config file for me, check afterwards that the change actually saved.
> - Put tunable numbers in one config file with a comment on each explaining what it does.

---

## What we ended up with

- **Detection:** YOLO11s, fine-tuned on the cat, running on all cameras in one GPU batch with ONNX Runtime,
  3 to 8 times a second (faster when it moves or is close, slower when it's still).
- **3D position:** box centres triangulated across cameras using the existing calibration; with only one
  camera, the bottom of the box is projected onto the floor. Smoothed with a One Euro filter and a jump gate.
- **SteamVR overlay app** (Python + `openvr`): a cat icon floating over its real position and a ring on the
  floor under it. The icon changes when it is resting (still 2 minutes) or running. The marker stays put
  when you drag or rotate your play space.
- **Proximity warning:** a small arrow at the edge of your view pointing toward it, plus a short controller
  buzz. It triggers on distance, on it moving near you, and on "time to contact" when one of you is closing in
  fast. A napping cat a little way off does not trigger it.
- **Training loop:** capture frames, auto-label, check labels by hand, fine-tune, and repeat. The tracker also
  saves "hard" frames by itself while running, so later rounds fix exactly what it gets wrong.
- **Quality of life:** starts automatically with SteamVR (headless), checks its own calibration every few minutes,
  restart/stop scripts, logs.
- **VRChat (optional):** sends its position to an avatar over OSC, so friends see a prop (a low poly snake, in our
  case) where it is.

---

## Architecture in one picture

```
cameras ──> YOLO (GPU, batched) ──> boxes per camera
                                     │
          existing calibration ──────┤  room filter + height filter
                                     ▼
                  triangulate (2+ cams) / floor-project (1 cam)
                                     ▼
                 One Euro filter, jump gate, confirm N frames
                                     ▼
               position in CAMERA space ──(anchor)──> SteamVR RAW space
                                     ▼
          every frame: raw -> current standing space (follows play space moves)
                                     ▼
       SteamVR overlays (icon, ring, edge arrow) + haptics  ·  OSC to VRChat
```

---

## Build order (what we did, in the order that worked)

### Phase 0: Feasibility plan
We started with a written plan before any code. Worth doing: it caught two bad ideas early (see Decisions).

### Phase 1: First working tracker, stock model
1. Separate folder inside (or beside) the existing camera project, reusing its camera, calibration and
   triangulation code by importing it. Nothing in the original project gets edited.
2. Stock YOLO11s exported to ONNX (fp16 weights), COCO class 15 = cat. Batch all cameras into one GPU run.
   Input 960 px long side: 640 missed small cats, 1280 was slower for no gain.
3. Locate: triangulate box centres when 2+ cameras see it (loose reprojection limit, ~40 px, since box centres
   from opposite sides aren't the exact same point). One camera: project the box's bottom edge to the floor,
   then push it ~20 cm further away (the bottom edge is its near side, not its middle).
4. **Anchor to SteamVR raw space** (see below). This is the key trick.
5. SteamVR overlay app showing an icon + floor ring at its position.
6. A `desktop_test` mode: same detection with the camera views on screen and no VR. Very useful for checking
   detection without putting a headset on.

### Phase 2: Fix the first real test
The first test ran but: missed it lying down, some cameras too dark, a painting on the wall detected as a cat.
- **Room filter:** throw out any detection whose floor point lands outside the box around the cameras (plus ~15 cm).
- **Height filter:** throw out anything triangulated above ~1 m (raise it if your pet climbs).
- **Own camera settings:** the body tracker wants a short exposure for sharp 120 fps frames; a cat tracker wants
  light. We doubled exposure (3.9 to 7.8 ms) and dropped to 30 fps, for the cat tracker's runs only.
- **White balance bug:** two cameras looked dark and blue while reporting the right white balance. The UVC
  driver echoed the requested value but kept an old one. Fix: at startup, toggle auto white balance on and off,
  then set the fixed value again. Log each camera's average colour so you can see this kind of thing.
- **Confirm frames:** require 2 to 3 detections in a row before showing it; fade the marker over ~8 s after it's lost.

### Phase 3: Teach the model your pet (the biggest win by far)
Stock COCO models learned from side-on internet photos. Ceiling cameras and a curled-up cat look nothing like
that. One fine-tuning round took us from roughly 1 of 4 cameras seeing it to all 4, every position triangulated.

1. **Capture:** save one frame per camera every 2 s while the pet wanders and naps (10 min = ~1200 images),
   with the stock model's guesses saved as starting boxes.
2. **Auto-label** (the user's idea, and a great one):
   - *Cross-camera:* where any camera found it, compute its 3D position and project its outline (a small
     cylinder, ~22 cm wide, ~30 cm tall) into the cameras that missed it. If a weak stock-model box overlaps
     that outline, use it instead (tighter).
   - *Gap filling:* if it was found before and after a gap, close in time (< 8 s) and in space (< 30 cm), it
     didn't move, so fill the gap. If it jumped further, leave those frames unlabelled.
   - Auto boxes show in a different colour so the human checks them. The projection can't know it's hidden
     behind the couch, so the human deletes those.
3. **Label tool** (OpenCV window): drag a box, right-click to delete, `z` undo, space = next, `x` = no pet here,
   backspace = back, `r` = reuse the box from this camera's previous frame (shown in blue; huge time saver
   while it sits still). Progress saved per session so you can stop any time. Only frames you explicitly
   pass count as checked.
4. **Train** in its own virtual environment (PyTorch + CUDA + Ultralytics, ~3.5 GB), so the main project's
   environment is never touched. One class (cat), 60 epochs, imgsz 960. Export to ONNX for the tracker.
5. **Empty frames matter.** Frames with no pet (or with the boxes on the painting/headset deleted) teach it what
   isn't a cat. Our best model used ~4200 images, ~1300 of them deliberate empty-room "bait".
6. **Hold-out:** hold out the last sixth of every session (by time), not every Nth frame (neighbouring frames
   are near-identical, so scores look perfect and mean nothing) and not the newest whole session (then it
   never trains on your newest data).
7. **Incremental rounds:** `train_more` starts from the last trained model and runs 20 epochs on all sessions
   (old + new, so it doesn't forget). A short capture aimed at one weak spot (the couch, under the desk)
   helps more than a long general one.
8. **Big run** when you have a lot of data: from the stock model, up to 100 epochs, early stop with patience 30.
   Ours stopped at 82, best epoch 52, precision 0.99, recall 0.97, mAP50-95 0.83.

### Phase 4: Better warnings
- A beep at 1 m was annoying. Replaced with a **head-locked arrow** near the edge of view (~32° off centre,
  1 m away, ~7 cm wide) pointing toward it, and its icon turns red.
- **Warn on more than distance:** always under 1 m; under 1.8 m only if it's moving; earlier if either of you is
  closing in fast enough to meet within 2.5 s (up to 4 m away). Ignore slow closing speeds (< 0.2 m/s).
- **Haptics** via SteamVR Input (an `actions.json` + bindings per controller type): one short L-R-L-R pattern
  each time the warning comes on, re-armed only after it's been off for 1 s. Constant buzzing drained batteries.
- **States with hysteresis:** "moving" starts above 0.2 m/s for 0.4 s and ends below 0.12 m/s for 1 s, so
  jitter can't flicker it. "Resting" after 2 minutes still, and the timer survives brief detection drops.
- Ease the shown position toward each new detection (~0.15 s) so the marker glides instead of jumping.

### Phase 5: Make it cheap and automatic
- **GPU:** the detector doesn't need body-tracking rates. Detection at 8 Hz when it moves or is close, 3 Hz
  otherwise; overlays are re-placed from the head pose 30 times a second, so it never looks choppy. A real fp16
  model (via `onnxconverter-common`, keeping the box-decoding head in fp32) roughly halved GPU work, boxes
  within 1 px. Result: GPU mostly under 20%.
- **Autostart with SteamVR:** register as a SteamVR overlay app (an `.vrmanifest` with auto-launch) that starts
  headless and reuses the saved anchor. Stop it with a stop-file the tracker polls.
- **Anchor self-check:** every 3 minutes, collect a few head sightings and compare with the headset. Warn (a
  notice in view) only if it's off by more than 10 cm twice in a row, only while the headset is actually worn,
  and only if the sightings are tightly grouped. Without those gates it gave false alarms.
- **Hard-frame mining:** while running, save a moment (all cameras) only when 2+ cameras are confident and
  another camera that should see it missed. This means it is definitely in the room and that camera
  is wrong. Cap it at 150 moments per run, 3 s apart, and stop below 10 GB free disk space. Then label and `train_more`.

### Phase 6 (optional): VRChat
- **Send its position relative to your head, not in world space.** VRChat's world position doesn't follow
  SteamVR play space moves, but "1.2 m ahead and 0.4 m to the right of my head" is always right.
- OSC to `127.0.0.1:9000`, sent from its own thread at ~60 Hz with a fresh headset pose each time. Parameters
  we used (floats divided by a 4 m range to fit -1..1):
  `CatAhead`, `CatRight`, `CatVisible`, `CatState` (0 normal, 1 resting, 2 moving), `CatNear`, plus room-frame
  `CatRoomX/Z`, `HeadRoomX/Z`, `HeadRoomYaw`, `CatRoomYaw` (heading from its movement) and `CatHeadingKnown`.
- Avatar side: a prop under a root that has a position constraint (Y frozen) and a Y-only rotation constraint
  to the head, with the prop offset driven by the parameters through a blend tree. We handed this to a separate
  avatar project with a written brief. An `osc_test` script that holds a fake cat 1 m ahead of you made lining
  it up easy.
- Your own SteamVR marker stays on regardless, so you see both where it really is and what others see.

---

## The anchor: the most important idea

Camera calibration is usually done in SteamVR **standing** space as it was on calibration day. But standing
space moves: play space tools move it constantly, and even without them we measured a ~30 cm drift.
SteamVR's **raw** space (`TrackingUniverseRawAndUncalibrated`) stays fixed to the base stations, just like the
cameras.

So:
1. Run your pose model for a few seconds while you walk around wearing the headset (at least ~0.8 m of
   walking, ~300 samples). Pair where the cameras see your head (eyes/ears triangulated) with the headset's raw pose
   plus a fixed headset-to-head offset.
2. Fit a rotation about the vertical axis plus a translation (camera space to raw space). Ours fit to 22 mm.
   Save it, and reuse it until cameras or base stations move.
3. Every frame, convert its raw position into the *current* standing space using SteamVR's current
   raw-to-standing transform, and place the overlay there.

If you don't have a body pose model, the same fit works with any point both systems see: a controller or tracker
held in view of the cameras, or a bright marker on the headset.

---

## Decisions and why

- **Not hijacking a spare tracker (like an elbow) for the pet.** VRChat assigns trackers to body joints at
  calibration, so it would be either ignored or bend your arm. Drivers like VMT are fine for prototyping only.
- **SteamVR overlay first, VRChat later.** The overlay works in every game, follows play space moves, and is the
  actual safety feature. VRChat is a nice extra.
- **Read-only access to the existing tracking project.** No risk of breaking the body tracking. The cost is that both
  can't use the cameras at once (only one program can open them). Merging cat detection into the body tracker
  is a possible later step.
- **No "ignore things that never move" filter.** It sounds good for false positives, but a sleeping cat never
  moves either. Use room/height filters and training on empty frames instead.
- **Weak detections count only where it's expected.** Boxes down to 0.08 confidence are accepted only if they
  overlap its projected outline from another camera or its last position. This cut flicker a lot.
- **Movement-based heading** for the VRChat prop instead of a pose model for facing (that would need much more labelling).

---

## Lessons learned / gotchas

- **Check which model is actually loaded.** A config edit silently reverted, and two "much better" test runs
  were really the stock model. Log `model loaded: <path>` at startup and look at it after every change.
- **Validation scores from one session are flattering.** 99/99 meant little until there were several sessions
  and a proper time-based hold-out. The live test is the real check.
- **Don't trust the camera's reported settings.** Measure the image (average R/G/B per camera).
- **Auto-labelling amplifies false positives.** If the stock model boxed a headset lying on the floor, auto-label
  will project that into every camera. For sessions like that, skip auto-label and fix by hand; those frames
  are valuable negatives.
- **Annoying alerts get turned off.** Visual edge arrow plus one short buzz was the version that stuck.
- **Body tracking rates aren't needed.** Detect a few times a second and re-place the overlay from the head pose
  at 30 Hz. It looks smooth and costs a fraction of the GPU.
- **Each training run overwrites the model.** Copy a good one somewhere safe before training again.
- **Cap anything that writes to disk** (captures, hard frames) by count and free space.
- **Iterate with real tests.** Most of the good ideas (auto-labelling, `r` to reuse a box, removing the beep, lower
  frame rate) came from the user trying it and reporting back. Short loops beat big plans.

---

## Starting numbers that worked for us

Treat these as starting points; your room, cameras and pet will differ.

| Setting | Value |
| --- | --- |
| Detector input | 960 px long side |
| Score / weak score | 0.2 / 0.08 (weak only near expected position) |
| Detection rate | 8 Hz moving/close, 3 Hz idle |
| Overlay update | 30 Hz |
| Triangulation reprojection limit | 40 px |
| Max height | 1.0 m |
| Room margin | 0.15 m |
| One Euro filter | min_cutoff 1.0, beta 0.8 |
| Max jump | 1.0 m unless repeated 2 times |
| Confirm / lost / fade | 2 detections / 1 s / 8 s |
| Warn | always < 1.0 m; moving < 1.8 m; time-to-contact < 2.5 s up to 4 m |
| Rest / move | still 120 s / > 0.2 m/s for 0.4 s, ends < 0.12 m/s for 1 s |
| Anchor check | every 180 s, warn > 10 cm twice in a row |
| Capture | 1 frame per camera every 2 s |
| Training | YOLO11s, imgsz 960, 60 epochs (first), 20 (`train_more`), 100 with patience 30 (big) |

---

## Suggested first message after pasting this

> Read the guide above. Then look at my camera project (I'll give you folder access) and tell me: what of my
> existing code you can reuse for camera capture, calibration and triangulation; whether I have a head/pose
> model for the anchor or need another reference; and a phase 1 plan for my setup. Don't change anything in my
> project folder.
