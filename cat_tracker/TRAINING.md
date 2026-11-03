# Training the detector on your cat

**You need to do this to get good results.** The stock YOLO model learned from internet photos, mostly of upright
cats seen from the side, not curled-up cats seen from the ceiling. It has never seen your cat, your room, your
lighting or your furniture.

How much training helps: with the stock model, about 1 camera in 4 saw it, and its position flickered.
After one round of training on about 15 minutes of footage, all 4 cameras saw it almost all the time and
every position was triangulated. Each later round fixed a specific weak spot, such as the couch.

The loop is: **capture → autolabel → label → train → test**, then repeat for anything it still misses. The first
round takes about an hour of your time plus 20 to 60 minutes of GPU time.

## Before you start

- The cameras are calibrated (see [CALIBRATION.md](../CALIBRATION.md)) and `desktop_test.bat` runs.
- An NVIDIA GPU. Training uses its own Python environment in `cat_tracker\.venv`, created on the first
  `train.bat` (about 3.5 GB, one time). The camera core's `.venv` is never touched.
- Some free disk space. 10 minutes of capture is about 1200 images (roughly 150 to 300 MB with 4 cameras).

All the `.bat` files below are in `cat_tracker\`. Double-click them, or run them from a terminal to add options.

## 1. Capture

Run `capture.bat` while your cat is in the room. It saves one frame from each camera every 2 seconds, with the
current model's guesses saved as starting boxes. You don't need SteamVR. Press `q` to stop. Each run is its own
session in `cat_tracker\captures\`. While the tracker runs, `c` also starts and stops capturing.

What to capture, roughly in order of value:

- **The cat lying down and sleeping**, in all its usual spots. This is what stock models miss most.
- **The cat walking and running** across the room.
- **Every spot it uses**: couch, bed, under the desk, the floor near where you stand to play.
- **Different lighting**: day, night, with your usual VR lighting.
- **The room without the cat** (a few minutes is enough). These frames teach it what *isn't* a cat. Include anything
  it has mistaken for the cat: pictures, plush toys, bags, the headset lying on the floor, laundry.

10 to 20 minutes is a good first session. Later, short sessions aimed at one weak spot do more than long general ones.

## 2. Autolabel (optional, saves a lot of time)

Run `autolabel.bat` before labelling. It fills in boxes the model missed, in two ways:

- **From other cameras:** where any camera found it, it works out where it is in 3D and draws its outline into
  the cameras that missed it.
- **From nearby moments:** if it was found before and after a gap, within 8 seconds and 30 cm, it didn't move,
  so it fills the gap. If it moved further, it leaves those frames alone.

Added boxes show **orange** in `label.bat`, so you check every one. The projection can't tell when it's hidden
behind furniture, so delete those.

**Skip autolabel for a session where the model boxed something that isn't the cat**, like a headset on the floor. It
would copy that mistake into every camera. Fix that session by hand instead.

## 3. Label

Run `label.bat`. It goes through every session with unchecked images, newest first, one camera image at a time.
You can stop at any time (`q`) and carry on later.

| Input | What it does |
| --- | --- |
| Left-drag | draw a box around it |
| Right-click in a box | delete that box |
| `z` | undo your last box or deletion |
| Space or Enter | the boxes are right: save, next image |
| `x` | no cat in this image: clear the boxes, next image |
| `r` | reuse the **blue** box (your box from this camera's previous image) and go on. One key per image while it sits still |
| Backspace | back one image |
| `j` | skip ahead 10 (skipped images stay unchecked and aren't used) |
| `q` or Esc | save and quit |

Colours: green boxes came from the model, orange from autolabel, blue is your previous box (only used if you press `r`).

Tips for good labels:

- **Snug boxes around its whole body**, tail included when you can see it. Be consistent.
- **If it's fully hidden, no box.** If it's partly visible, box the part you can see.
- **Check the empty frames too.** Pressing `x` or deleting a wrong box and pressing Space is a useful label: it
  teaches the model that this isn't a cat. Our best model had about 2900 images with it and 1300 without.
- **Be careful with `r` near a false detection.** It copies the whole previous box.
- Only images you pass with Space, Enter, `x` or `r` count. The bottom line shows how many you've checked.

A few hundred checked images with it in them is enough for a big first improvement. Under 50 and it warns you.

## 4. Train

| Script | When to use it |
| --- | --- |
| `train.bat` | **The first time.** Starts from `models\yolo11s.pt`, 60 epochs on every checked image. |
| `train_more.bat` | **After adding a session.** Starts from your last trained model, 20 epochs, on *all* sessions (old and new, so it doesn't forget). About a third of the time. |
| `train_big.bat` | **When you have a lot of data** (thousands of images). Fresh start, up to 100 epochs, stops early once it stops improving. About an hour. |

Keep the PC awake while it trains. At the end it:

- prints **precision** (how many of its boxes were really the cat) and **recall** (how often it found the cat) on held-out
  images: the last sixth of every session, which it didn't train on.
- saves `models\cat_finetuned.onnx` and `models\cat_finetuned_half.onnx` (the one the tracker uses, about half
  the GPU work).

The scores are usually flattering, because held-out frames come from the same sessions. The live test is what counts.

**Switch the tracker to your model** (once): in `cat_tracker\config.yaml`, under `detector`, set
`model: cat_tracker/models/cat_finetuned_half.onnx` and `cat_class: 0`. Later training runs overwrite that
file, so no change is needed after that.

**Back up a good model.** Every run overwrites `cat_finetuned*.onnx`. Copy one you like somewhere safe first.

## 5. Test

Run `desktop_test.bat` with it in the room. First check that the console says
`Cat model loaded: cat_tracker/models/cat_finetuned_half.onnx`. That line is the only way to be sure which model
is running. Then look at how many cameras box it, and whether the position holds steady when it sits still.

## 6. Keep improving

- **Hard frames are collected for you.** While the tracker runs, it saves moments where two or more cameras are
  sure of it but another camera that should see it missed. They go into `captures\<date>-<time>-hard`, at most
  150 moments per run, and only with 10 GB free. Their missing boxes are already filled in (orange), so skip
  autolabel and go straight to `label.bat`, then `train_more.bat`.
- **Aim at weak spots.** If it misses the cat on the couch, capture two minutes of the cat there, label, `train_more`.
- **False alarms?** Capture the empty room with whatever fooled it in view, label those frames as empty, `train_more`.
- Every few rounds, when you have a lot of images, do a `train_big.bat` run.

## Troubleshooting

- **`train.bat` setup failed:** delete `cat_tracker\.venv` and run it again. It needs Python 3.12 (`py -3.12`).
- **"No checked images yet":** run `label.bat` and pass some images with Space, `x` or `r`.
- **Training didn't seem to help:** check the `Cat model loaded` line. A config that still points at the old model
  is an easy mistake to make.
- **Out of GPU memory:** `train.bat --batch 4`.
