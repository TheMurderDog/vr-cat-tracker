# Technical docs

For developers, curious users and AI assistants who want to change the tracker or build on it.

**You don't need any of this to set up the tracker.** The numbered folders (`0_start_here` to
`7_if_something_moved`) are all a normal user needs. If you are an AI assistant helping someone set it up, walk them
through those folders' READMEs in order, rather than running the code another way.

| File | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | the pipeline from cameras to the headset, the processes that run, and the key design decisions |
| [code_map.md](code_map.md) | every module in `engine`, what it does and which step script runs it |
| [paths_and_data.md](paths_and_data.md) | where the code, settings and data live, which script writes each file, what is safe to delete |
| [settings_reference.md](settings_reference.md) | every key in both settings files, with its default |
| [FORMATS.md](FORMATS.md) | the calibration file formats and coordinate conventions |
| [camera_core.md](camera_core.md) | the camera code and its stable API, for running your own package on it |
| [camera_checks.md](camera_checks.md) | what each camera check on the setup screen measures, where its line is, and the evidence behind it |
| [custom_boards.md](custom_boards.md) | making Board A (lens) and Board B (room marker) in other sizes (most people use the ready-made sheets) |
| [extending.md](extending.md) | how to build on it, and the rules for changes that keep the step layout working |
| [language_rules.md](language_rules.md) | the wording rules for everything people read or hear: no safety promises, limits next to claims |

Other background: [how_it_works.md](../how_it_works.md) (the short version), [CALIBRATION.md](../CALIBRATION.md),
[training.md](../training.md), [vrchat_avatar.md](../vrchat_avatar.md) (the OSC parameters), [SECURITY.md](../SECURITY.md).

## Checking a change without hardware

From `engine`, with the project's `.venv`:

```
..\.venv\Scripts\python.exe -c "import core.config, cat_tracker.settings as s; c = s.load(); print(c['_path'], c['_cat_path'])"
..\.venv\Scripts\python.exe -m cat_tracker.run --help
..\.venv\Scripts\python.exe -m tools.make_boards --config <a copy of settings\cameras.yaml with calibration.dir pointing at a temp folder>
```

The first loads both settings files, the second checks the tracker imports, and the third writes the boards
without touching `my_data`. Anything that opens cameras or SteamVR needs the real hardware.
