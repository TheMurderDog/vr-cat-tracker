# Cat tracker

The cat tracker part of this repo. Setup, scripts and how it works are in the [main README](../README.md),
and the story of how it was built is in [docs/build_guide.md](../docs/build_guide.md).

Run its scripts from this folder. Each one changes to the folder above and runs `python -m cat_tracker.<name>`
with the camera core's `.venv`, so the paths in `config.yaml` are relative to the top-level folder.
