# my_data

Everything the tracker makes on your PC goes here, filled in as you go through the steps. None of it is in git, and
none of it is ever sent anywhere.

| Folder | What's in it | Made in |
| --- | --- | --- |
| `calibration` | the printable boards, lens and room calibration results, and reference pictures from each camera | step 2 |
| `models` | the stock model, and the models you train | steps 3 and 4 |
| `captures` | camera frames of your cat for training, and the "hard" frames saved while the tracker runs | steps 4 and 5 |
| `training` | the training data set and every training run (big; safe to delete between rounds) | step 4 |
| `backups` | the old `settings\cat_tracker.yaml`, copied each time training switches it to a new model | step 4 |
| `tracker` | the anchor (`anchor.json`) and small files the running tracker uses to talk to its watchdog | step 5 |
| `app` | the optional app's settings (alerts, marker look), the room heatmap and pictures it draws for VR | step 5 (the app) |
| `logs` | a log for every run, and snapshots (`cameras` for steps 1, 2 and 7, `cat_tracker` for the tracker, `cat_app` for the app) | every step |

- **Back up your setup:** copy this folder and the `settings` folder.
- **Start over:** delete this folder (keep this README if you like). Delete only `calibration` to redo step 2, or only
  `tracker\anchor.json` to redo the anchor.
- **Privacy:** `captures`, `logs` and `calibration` contain pictures of your room and anyone in it. Think twice before
  sharing them.
