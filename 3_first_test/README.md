# 3. First test

Check the tracker can find your cat, on the desktop. No headset needed.

## Before you start

- [ ] Step 2 done.
- [ ] About 4 GB of free disk space (a one-time download, step 4 uses it too).
- [ ] Your cat in the room.

## Run these in order

1. `1_get_stock_model.bat` - downloads the detector the tracker starts with. The first time takes 10 to 20 minutes.
2. `2_desktop_test.bat` - shows every camera with a box around your cat when it's found. `q` quits.

## You're done when

A box appears around your cat in at least one camera.

It **will** miss a lot for now. That's expected: step 4 teaches it your cat.

## If something's wrong

- **"Every camera must open":** close the camera setup screen, or anything else using the cameras.
- **Never a box, even with the cat in plain view:** add light, or set a longer `exposure_ms` under `cameras` in
  `settings\cat_tracker.yaml` (try `7.8`).
- **Getting the model failed:** delete the `.venv-train` folder in the top folder, then run `1_get_stock_model.bat`
  again.

## Next

Open [4_teach_it_your_cat](../4_teach_it_your_cat/README.md).

## Your notes

<!-- Leave notes here as you go: anything confusing, broken or missing. -->
