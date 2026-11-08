# Contributing

Thanks for wanting to help. This is a free hobby project run by one person (TheMurderDog), so reviews can take a
while. Small, focused changes get merged fastest.

If you only want to **use** the tracker, you don't need this page: open `0_start_here` and follow the numbered folders.

## What this project is for

This repository is a starting point that anyone can build on. Its one job is to be the **easiest way in**: an average
VR user who has bought the cameras should be able to get from download to seeing their cat in the headset by following
the folders. It can take some effort, but they shouldn't hit a technical wall.

So when a change makes the tracker smarter but setup harder, **lower friction wins**. That doesn't mean the idea is
turned away:

- **Make it optional.** Advanced tools, extra hardware support and power-user settings are welcome as an option that
  isn't the first thing a newcomer sees (a subfolder, a setting, or a page in `docs`).
- **Or build it outside.** It's open source. You're free to fork it, rebuild the architecture, or make a separate
  plugin or tool on top of it. You don't need permission, and you don't owe anything back. The AGPL-3.0 license does
  ask anyone who shares a changed version to share its source too; that's a license term, not a favour to anyone.

**Beyond cats.** Other pets, other animals, other headsets and other camera setups are welcome. Describe them the way
they're meant to be used: a free hobby tool that helps you notice an animal while you play. Contributions that pitch
it as a safety device, a security camera, or something for watching people won't be merged.

## Before you start

- **Open an issue first** for anything bigger than a typo or a small fix, so we can agree on the idea before you spend
  time on it.
- Read [AGENTS.md](AGENTS.md) and [docs/technical/README.md](docs/technical/README.md). They cover the architecture,
  where each module lives, and how paths and settings work.
- The tracker runs on Windows 10/11 with Python 3.12, an NVIDIA GPU, USB webcams and SteamVR. Many changes can be
  checked without that hardware (see [Testing](#testing)), but say in your pull request what you could and couldn't test.

## How the project is laid out

**The folders are the setup guide.** A newcomer opens `0_start_here`, then goes through `1_connect_cameras` to
`7_if_something_moved` in order. Keep that working:

| Where | What goes there |
| --- | --- |
| `0_start_here` ... `7_if_something_moved` | Only a `README.md` and numbered `.bat` launchers, in the order people run them. No code. |
| `engine` | All the code. Launchers change into `engine` and run `..\.venv\Scripts\python.exe -m <module>`. |
| `settings` | The two files people edit: `cameras.yaml` and `cat_tracker.yaml`. Defaults only, no secrets, no personal values. |
| `my_data` | Everything made on the user's PC (calibration, anchor, captures, models, logs). Kept out of git. |
| `docs`, `docs/technical` | How it works, licenses, security, and the detail developers and AI assistants need. |

Rules that follow from this:

- **A new user-facing tool gets a numbered launcher in the right step folder**, and the step's README says when to
  run it. When it finishes, it prints the next step.
- **When behaviour changes, update that step's README** in the same pull request.
- Resolve paths with `core.config.resolve_path`. Don't hard-code them.
- Never commit `my_data`, `.venv`, `.venv-train`, model files (`*.pt`, `*.onnx`) or your own settings values.

More detail: [docs/technical/extending.md](docs/technical/extending.md).

## Keep the setup path simple

Step READMEs are for someone who has never used Python or a terminal. They say what the step does, what you need, which
file to double-click, how you know you're done, and where to go next. That's all.

- Short sentences, plain words, no jargon. If a step needs explaining, explain it in `docs` and link to it.
- Technical detail, settings explanations, design notes and anything written mainly for developers or AI assistants
  go in `docs/technical`, not in the step folders.
- Optional or advanced features stay out of the main path. If most people don't need it, it goes in a subfolder
  (like `later_rounds`) or in `docs`.
- New features that have only been tried on one setup are marked **(experimental)** next to where they appear.

## Wording rules

Everything people read or hear follows [docs/technical/language_rules.md](docs/technical/language_rules.md): READMEs,
on-screen text, voice lines, log messages, issue and pull request text. In short:

- This is a hobby project, **not a safety device**. Say "helps you notice your cat", "tries to", "where the cameras
  think it is". Don't say safe, protects, always, guaranteed, accurate, exactly or "will warn you".
- Put a limit next to every claim, and say where any number came from (one room, one cat, one day; other setups
  differ).
- Physical steps get one short precaution, written as an instruction ("Clear the floor first.").
- Installers keep the typed-YES disclaimer prompt.

Before you open a pull request, search your changed text for: `safe`, `safety`, `always`, `never`, `guarantee`,
`protect`, `prevent`, `ensure`, `reliable`, `accurate`, `exactly`, `really is`, `will warn`, `100%`. Each hit should
either describe a limit or be reworded using the table in the rules.

## Privacy

The cameras see people's homes, so:

- **No telemetry, uploads, audio recording or new network output** without a privacy discussion in an issue first.
  Today the only network output is VRChat OSC to `127.0.0.1`, and the tracker opens no listening ports.
- Anything that saves pictures says so on screen or in the log when it starts.
- No admin rights. Network downloads happen only during install or training, from pinned versions where possible.
- **Don't put pictures from your own `my_data` in issues, pull requests or test files.** Text from logs is fine.

See [docs/SECURITY.md](docs/SECURITY.md). Report security problems privately through the repository's Security tab.

## New dependencies, models and voices

- Add each new Python package, model file or voice to [docs/NOTICE.md](docs/NOTICE.md), with where it comes from and
  its license.
- **The license must be compatible with AGPL-3.0** (the project's license, because it uses Ultralytics YOLO11).
  MIT, BSD, Apache-2.0, GPL-3.0 and LGPL are fine. Anything "non-commercial", "research only" or with no license is
  not.
- Model files aren't committed to the repository. Download them at setup time from the original source, with a pinned
  version and a checksum where possible.
- A model's training data can carry its own terms. Check them and note them in NOTICE.md.
- Prefer what's already installed over adding a new package.
- New product or brand names go on the DISCLAIMER's "Not affiliated" list.

## Testing

**Without hardware.** From `engine`, with the project's `.venv`:

```
..\.venv\Scripts\python.exe tests\test_ultra_imports.py
..\.venv\Scripts\python.exe -m cat_tracker.run --help
```

The tests in `engine/tests` are plain Python scripts (no pytest needed), so run each one directly. New tests should
work the same way and must not open cameras or SteamVR.

[docs/technical/README.md](docs/technical/README.md) has a few more checks that load the settings and write the boards
without touching `my_data`.

**With hardware.** Anything that opens cameras, SteamVR or the overlay needs a real test. Say in the pull request what
you tried: number of cameras, headset, GPU, and what you saw. Changes that affect the tracker in the headset get tested
on the reference setup before they're merged.

**Model and detection changes** (training settings, a new base model, autolabelling, detector thresholds) are
checked against a **test session**: a capture session that is marked as the test set (`"role": "test"` in its
`session.json`, see `train_extras.py`). Training never uses a marked test session. At the end of every run,
`4_teach_it_your_cat\3_train.bat` scores the old and new models on it and keeps the better one.

- Mark a capture from a different day as your test session. Run
  `4_teach_it_your_cat\later_rounds\score_test_set.bat` (read-only) with the old and new models, and put its
  "box on the cat" and false-alarm numbers in the pull request. Numbers come from one room and one cat; other setups differ.
- Label the test session by hand. Autolabelling or helper models must never label it, or the score only measures how
  well a model agrees with itself.
- The maintainer also scores the change with the same tool on their own test session (about 700 labelled pictures, never trained on).
  Those are pictures of a home, so they aren't in the repository. Never send pictures from `my_data`.
- A change that finds the cat less often doesn't get merged, even if it's faster.

**Camera checks** (the setup screen's GOOD / FOCUS? / A BIT DARK states) err on the side of warning. A change that
could show a check as passed when it shouldn't needs evidence: see
[docs/technical/camera_checks.md](docs/technical/camera_checks.md).

## Pull requests

1. Fork, make a branch, keep it to one change.
2. Fill in what changed, why, and how you tested it (with or without hardware).
3. Sign off your commits (see [License and sign-off](#license-and-sign-off)), and check the wording search above, NOTICE.md for new dependencies, and the step README if behaviour changed.
4. TheMurderDog decides what gets merged. Reviews are done with the help of an AI assistant, which reads the change
   and checks it against this page. Changes to the tracker, calibration or detection are tried on real hardware with a
   real cat before merging, which can take a few days. Expect questions; it's not a rejection.
5. Before merging, the maintainer may add small commits to your pull request to keep the project consistent, for
   example rewording text to match the wording rules or moving a file to the folder it belongs in. Following this page
   as closely as you can keeps that to a minimum and gets your change merged sooner.
6. If you used an AI assistant, that's fine (most of this project was written with one). You're still responsible for
   understanding and testing what you send.

**Changes that won't be merged**, however good the code: anything that weakens the DISCLAIMER, removes the typed-YES
install prompt, breaks the wording rules, adds telemetry or uploads without a privacy discussion, or makes the first-time
setup harder without making it optional.

The project may change hands one day, or a fork may take over. That's fine: the goal is that it exists and people can
build on it.

### License and sign-off

By sending a pull request, you agree your contribution is published under the project's license (AGPL-3.0, or MIT
for the VRChat avatar files in `6_optional_vrchat/1_import_into_unity`).

**Sign off each commit** with `git commit -s`. This adds a `Signed-off-by:` line confirming you wrote the change, or
have the right to send it, under the project's license (the [Developer Certificate of Origin](https://developercertificate.org)).
If you write code for an employer or a company you own, check that you're allowed to share it first. A GitHub noreply
email address is fine for the sign-off.

## Be kind

Be patient and polite in issues and reviews. If someone reports that they or their pet got hurt, don't reply about
blame; leave it to the maintainer.
