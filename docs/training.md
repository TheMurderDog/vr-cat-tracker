# Training the detector on your cat

**You need to do this to get good results.** The stock YOLO model learned from internet photos, mostly of upright
cats seen from the side, not curled-up cats seen from the ceiling. It has never seen your cat, your room, your
lighting or your furniture.

How much training helps: with the stock model, about 1 camera in 4 saw it, and its position flickered.
After one round of training on about 15 minutes of footage, all 4 cameras saw it almost all the time and
every position was triangulated. Each later round fixed a specific weak spot, such as the couch.

The loop is: **capture → label (autolabel runs first, by itself) → train → test**, then repeat for anything it still misses. The first
round takes about an hour of your time plus 20 to 60 minutes of GPU time.

## Before you start

- The cameras are calibrated (see [CALIBRATION.md](CALIBRATION.md)) and `3_first_test\2_desktop_test.bat` runs.
- An NVIDIA GPU. Training uses its own Python environment, `.venv-train` in the top folder, created by
  `3_first_test\1_get_stock_model.bat` or the first `4_teach_it_your_cat\3_train.bat` (about 3.5 GB, one time). The main `.venv` is never touched.
- Some free disk space. 10 minutes of capture is about 1200 images (roughly 150 to 300 MB with 4 cameras).

The `.bat` files below are in `4_teach_it_your_cat` (and its `later_rounds` folder). Double-click them, or run
them from a terminal to add options.

## 1. Capture

Run `4_teach_it_your_cat\1_capture.bat` while your cat is in the room. It saves one frame from each camera every 2 seconds, with the
current model's guesses saved as starting boxes. You don't need SteamVR. Press `q` to stop. Each run is its own
session in `my_data\captures\`. While the tracker runs, `c` also starts and stops capturing.

What to capture, roughly in order of value:

- **The cat lying down and sleeping**, in all its usual spots. This is what stock models miss most.
- **The cat walking and running** across the room.
- **Every spot it uses**: couch, bed, under the desk, the floor near where you stand to play.
- **Different lighting**: day, night, with your usual VR lighting.
- **The room without the cat** (a few minutes is enough). These frames teach it what *isn't* a cat. Include anything
  it has mistaken for the cat: pictures, plush toys, bags, the headset lying on the floor, laundry.

10 to 20 minutes is a good first session. Later, short sessions aimed at one weak spot do more than long general ones.

## 2. Autolabel (by itself, when labelling starts)

`4_teach_it_your_cat\2_label.bat` runs it the first time it opens a session that has pictures to decide ("Preparing
boxes...", progress in the window), and again only if the session was autolabelled the old way. Only sessions from the
current camera setup (it projects with today's room calibration); pictures you've decided or skipped are never
changed. It fills in boxes the model missed, in two ways:

- **From other cameras:** where any camera found it, it works out where it is in 3D and draws its outline into
  the cameras that missed it.
- **From nearby moments:** if it was found before and after a gap, within 8 seconds and 30 cm, it didn't move,
  so it fills the gap. If it moved further, it leaves those frames alone.

Added boxes show **orange** in `4_teach_it_your_cat\2_label.bat`, so you check every one. The projection can't tell when it's hidden
behind furniture, so delete those.

**Skip autolabel for a session where the model boxed something that isn't the cat**, like a headset on the floor. It
would copy that mistake into every camera: open it with `2_label.bat --no-autolabel` and fix it by hand.

To run it again by hand (advanced: it redoes only its own undecided boxes, backed up first), from the `engine` folder:
`..\.venv\Scripts\python.exe -m cat_tracker.autolabel --session <name>` (`--dry-run` only reports).

## 3. Label

Run `4_teach_it_your_cat\2_label.bat`. It goes through every session with unchecked images, newest first, one camera image at a time.
You can stop at any time (`q`) and carry on later.

| Input | What it does |
| --- | --- |
| Click on the cat | snap a box to it (the stock model on an enlarged crop there); replaces a box under the click |
| Drag on an empty spot | draw a box |
| Drag a box's corner or side / its middle | resize / move it (handles light up on hover) |
| Right-click in a box | delete that box |
| Mouse wheel | zoom in and out around the cursor |
| `Z` | undo (boxes, edits, deletions) |
| Space | the boxes are right: save, next image |
| `S` | no cat in this image: clear the boxes, next image |
| `D` | not sure: skip it (kept, but left out of training: skipped.txt), next image |
| `W` | copy the **blue** box (your box from this camera's previous image) as a green one; Space then goes on |
| Middle-drag / ? HELP | move the zoomed view / a help window with every feature, the box kinds drawn, and the sliders |
| `A` | back one image |
| `H` | the hint on or off: on a picture with no box, a magenta cross (and a faint cat-sized outline) where the other cameras place the cat at that moment |
| `Q` or Esc | save and quit |

The old keys still work (Enter, `x`, `r`, Backspace, `j` = ahead 10), except `s`, which is now "no cat". Three sliders
set the blue box's, the other boxes' and the hint's opacity (kept in `my_data/label_prefs.json`). Colours: green boxes came from
the model, orange from autolabel ("CHECK THIS" when it wasn't sure), blue is your previous box (only used with `W`).

Tips for good labels:

- **Box only what you can see**, tight around the fur; leave a sticking-out tail outside the box. Be consistent.
- **If it's fully hidden, no box** (`S`). Can't tell whether it's the cat: `D`, so it isn't used either way.
- **Check the empty frames too.** Pressing `S` or deleting a wrong box and pressing Space is a useful label: it
  teaches the model that this isn't a cat. Our best model had about 2900 images with it and 1300 without.
- **Be careful with `W` near a false detection.** It copies the whole previous box.
- Only images you pass with Space, `S` or `W` count. The bottom line shows how many you've checked.

A few hundred checked images with it in them is enough for a big first improvement. Under 50 and it warns you.

## 4. Train

| Script | When to use it |
| --- | --- |
| `4_teach_it_your_cat\3_train.bat` | **The first time.** Starts from `my_data\models\yolo11s.pt`, 60 epochs on every checked image. |
| `4_teach_it_your_cat\later_rounds\train_more.bat` | **After adding a session.** Starts from your last trained model, 20 epochs, on *all* sessions (old and new, so it doesn't forget). About a third of the time. |
| `4_teach_it_your_cat\later_rounds\train_big.bat` | **When you have a lot of data** (thousands of images). Fresh start, up to 100 epochs, stops early once it stops improving. About an hour. |
| `4_teach_it_your_cat\later_rounds\train_overnight.bat` | **A long run, overnight.** Up to 300 epochs, stops early once it stops improving (50 epochs without), at most 6 hours. Keeps Windows from sleeping while it runs. Interrupted (a restart, a power cut)? Run it again: it picks up from the run's `last.pt`. |

At the end it:

- scores the new model and the one in use **on the same held-out pictures**, and only switches to the new one if it
  finds the cat better (F1, by at least 0.01). It says plainly which it kept and why. A model that wasn't kept is saved
  in `my_data\models\candidates`.
- holds out **whole sessions** for that score (`my_data\training\test_sessions.txt`): the first time there are checked
  sessions from two different days, the smallest one (40+ pictures) not from the day of the biggest is chosen and kept
  from then on, and marked **TEST SET: not trained on** on the 2_label sessions screen. A marked session is held back
  as soon as it's marked, even half labelled. To pick one yourself (best: a short capture on another day), run
  `python -m cat_tracker.sessions --test <session name>` from `engine` (`--not-test` undoes it). Only sessions from the current camera setup count (made after the last room calibration):
  old angles never judge a model meant for the new ones. Without a fair test set it uses the new model (it's trained on
  what the cameras see now) and says it couldn't compare fairly yet. Until then it scores on the last sixth of each session and says the score is NOT reliable: those
  pictures look just like the ones it trained on (old runs scored 0.99 after one epoch).
- when it keeps the new model: backs up the old model files to `my_data\backups\models_<time>`, saves
  `my_data\models\cat_finetuned.onnx`, `cat_finetuned_half.onnx` (the one the tracker uses, about half the GPU work) and
  `cat_finetuned.pt` (so the next run can be compared with it).
- writes everything it said to `my_data\training\training_log.txt`, and a short summary per run (`summary_<run>.txt`).

**Sessions.** Every labelled session is one folder in `my_data\captures`: `images\`, `labels\`, `checked.txt`,
`skipped.txt`, `auto.json` and `session.json` (its date, source: a capture, the tracker's hard moments or imported;
camera setup: current or older, by the last room calibration; counts; the autolabel method).
`python -m cat_tracker.sessions` lists them and refreshes `session.json`;
`python -m cat_tracker.sessions --import D:\old\captures` copies labelled sessions from another folder in as
"imported" (that folder is only read). Training uses every checked picture in `my_data\captures`.

**Reviewing.** In `2_label.bat`, SESSIONS (or Tab) opens a screen with every session in two lists: waiting for labels
(pictures still undecided) and done. A row shows the date, the source, the camera setup and "decided X / Y". The chips
at the top choose which pictures open (all, with cat, no cat, skipped, check this, more boxes than cats, possible
mistakes: saved as no cat where the other cameras see the cat). Hints and the possible-mistakes check only work for
sessions from the current camera setup (they use its room calibration). Clicking a
waiting session opens its first undecided picture; a done one (or any filter but All) opens for review, with
"reviewed X / Y", after its labels, `checked.txt`, `skipped.txt` and `auto.json` are copied to
`my_dataackups\labels-<session>-<time>`. "Practice copy" opens a throwaway copy in `my_data\practice` (a red band,
"PRACTICE COPY"), deleted when the tool closes. "Open folder" shows the session in Windows Explorer. The folders never
move: the lists are worked out from what's decided. `label --sessions` opens on this screen.

**Older labelled pictures and a starting model.** Every checked session in `my_data\captures` is used. To also train on
labelled sessions kept somewhere else (an older camera setup, read only) or to start from an earlier model, write
`my_data\training\defaults.json`, for example
`{"extra_captures": ["D:/old/captures"], "start_from": "D:/old/best.pt"}`. Those older sessions only ever train; the fair
test set is always from the current camera setup.

**GPU temperature.** Its temperature and power are logged every minute (from `nvidia-smi`), and the summary says how
hot it got: "GPU peaked at 78 C". Above 85 C it adds "running warm, check the fans and dust". Training keeps the card
at full load for hours. Cards slow their own clocks near their limit, but that relies on the PC's cooling working, so
run long training only with clean fans and clear vents. Training doesn't slow or pause anything itself. If you want
the card to run cooler, you can lower its power limit yourself in an administrator prompt, for example `nvidia-smi
-pl 220` (watts; `nvidia-smi -q -d POWER` shows the allowed range). The tracker never changes it.

**It switches the tracker to your model by itself** (when it keeps it): `settings\cat_tracker.yaml`, under `detector`,
gets `model: my_data/models/cat_finetuned_half.onnx` and `cat_class: 0`, and the old file is copied to `my_data\backups`
first.

## 5. Test

Run `3_first_test\2_desktop_test.bat` with it in the room. First check that the console says
`Cat model loaded: my_data/models/cat_finetuned_half.onnx`. That line is the only way to be sure which model
is running. Then look at how many cameras box it, and whether the position holds steady when it sits still.

## 6. Keep improving

- **Hard frames are collected for you.** While the tracker runs, it saves moments where two or more cameras are
  sure of it but another camera that should see it missed. They go into `my_data\captures\<date>-<time>-hard`, at most
  150 moments per run, and only with 10 GB free. Their missing boxes are already filled in (orange), so
  autolabel doesn't run on them: go straight to `4_teach_it_your_cat\2_label.bat`, then `4_teach_it_your_cat\later_rounds\train_more.bat`.
- **Aim at weak spots.** If it misses the cat on the couch, capture two minutes of the cat there, label, `train_more`.
- **False alarms?** Capture the empty room with whatever fooled it in view, label those frames as empty, `train_more`.
- Every few rounds, when you have a lot of images, do a `4_teach_it_your_cat\later_rounds\train_big.bat` run.

## Troubleshooting

- **`4_teach_it_your_cat\3_train.bat` setup failed:** delete the `.venv-train` folder in the top folder and run it again. It needs Python 3.12 (`py -3.12`).
- **"No checked images yet":** run `4_teach_it_your_cat\2_label.bat` and pass some images with Space, `S` or `W`.
- **Training didn't seem to help:** check the `Cat model loaded` line. A config that still points at the old model
  is an easy mistake to make.
- **Out of GPU memory:** `4_teach_it_your_cat\3_train.bat --batch 4`.
