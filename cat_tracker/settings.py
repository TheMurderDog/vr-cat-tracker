"""Load the camera core's config.yaml (read only) and the cat tracker's own config.yaml on top of it."""

from pathlib import Path

import yaml

from core.config import load_config

HERE = Path(__file__).resolve().parent
CAT_CONFIG = HERE / "config.yaml"


def load(core_config=None, cat_config=None):
    """the camera core's config with a "cat" section holding ours. Our logging section replaces the camera core's, so the cat
    tracker logs (and prunes old logs) only under cat_tracker/logs, and our cameras section
    overrides the camera core's camera settings in memory for this run."""
    cfg = load_config(core_config)
    path = Path(cat_config) if cat_config else CAT_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        cat = yaml.safe_load(f)
    if not isinstance(cat, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    cfg["logging"] = cat.pop("logging")
    # camera settings for the cat tracker only (e.g. a longer exposure); the core's own config.yaml is
    # never written, and other programs set its own values again whenever it opens the cameras
    cfg["cameras"] = {**cfg["cameras"], **(cat.pop("cameras", None) or {})}
    cfg["cat"] = cat
    cfg["_cat_path"] = str(path)
    return cfg
