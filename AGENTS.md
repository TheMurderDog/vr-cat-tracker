# AGENTS.md

VR cat tracker: USB webcams find a cat, triangulate it, and show it in SteamVR (and optionally VRChat over OSC).
Windows, Python 3.12, NVIDIA GPU.

- **Wording:** everything people read or hear (READMEs, on-screen text, voice lines, logs, GitHub text, posts) follows
  [docs/technical/language_rules.md](docs/technical/language_rules.md). It's a hobby project, never a safety device.
- Start with [docs/technical/README.md](docs/technical/README.md). It links the architecture, code map, paths, settings
  and the rules for changes.
- To help someone set it up, walk them through the numbered folders' READMEs (`0_start_here` to `7_if_something_moved`)
  in order.
- Layout: step folders hold only a README and numbered launchers. All code is in `engine`. Settings are in `settings`.
  Everything made on the PC is in `my_data`.
- Launchers change into `engine` and run `..\.venv\Scripts\python.exe -m <module>`. Paths resolve from the top folder
  with `core.config.resolve_path`. Never hard-code them.
- When behaviour changes, update the step's README, and make the launcher print the next step.
- The two printed sheets are **Board A** (the lens checkerboard, `calibration.boards.small`) and **Board B** (the
  room marker card, `calibration.room`). Everything people read or hear uses those names.
- Never commit `my_data`, `.venv` or `.venv-train`, and never put secrets in `settings`.
- No admin rights, no listening ports, and network output only to `127.0.0.1`.
