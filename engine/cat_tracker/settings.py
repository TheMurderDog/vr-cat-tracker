"""Load settings/cameras.yaml (read only) and the cat tracker's own settings/cat_tracker.yaml on top of it."""

from pathlib import Path

import yaml

from capture.camera import AUTO_FPS, MIN_FPS, fps_list
from core.config import REPO_ROOT, load_config

CAT_CONFIG = REPO_ROOT / "settings" / "cat_tracker.yaml"


def load(core_config=None, cat_config=None):
    """the camera core's config with a "cat" section holding ours. Our logging section replaces the camera core's, so the cat
    tracker logs (and prunes old logs) only under my_data/logs/cat_tracker, and our cameras section
    overrides the camera core's camera settings in memory for this run."""
    cfg = load_config(core_config)
    path = Path(cat_config) if cat_config else CAT_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        cat = yaml.safe_load(f)
    if not isinstance(cat, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    cfg["logging"] = cat.pop("logging")
    # camera settings for the cat tracker only (e.g. a longer exposure); settings/cameras.yaml is
    # never written, and other programs set its own values again whenever it opens the cameras
    own = cat.pop("cameras", None) or {}
    notes = []
    mode = str(own.get("fps", "full")).lower()
    if mode == "full":  # the default: the same speed as setup and calibration (settings/cameras.yaml)
        own = {k: v for k, v in own.items() if k != "fps"}
    elif mode == "auto":
        # EXPERIMENTAL: ask for 30, as the tracker looks a few times a second. capture.camera.Camera falls back
        # to the normal speed if the frames at 30 don't arrive, are black or frozen, or aren't the calibrated size;
        # a camera that ignores the request keeps its own speed (Camera.tell_speed logs what it really gives)
        own = {**own, "fps": [AUTO_FPS] * len(cfg["cameras"]["ids"]), "fps_full": cfg["cameras"].get("fps", 30)}
        notes.append("cameras.fps: auto (experimental): asking every camera for %d fps" % AUTO_FPS)
    else:
        asked = fps_list({"ids": cfg["cameras"]["ids"], "fps": own["fps"]})
        if min(asked) < MIN_FPS:
            notes.append(f"cameras.fps {own['fps']} in {path.name} is below the tracker's minimum of {MIN_FPS}; "
                         f"using {MIN_FPS} where it was lower")
            print("Note: " + notes[-1])
        own = {**own, "fps": [max(MIN_FPS, f) for f in asked]}
    cfg["cameras"] = {**cfg["cameras"], **own}
    cfg["cat"] = cat
    cfg["_cat_path"] = str(path)
    cfg["_notes"] = notes  # logged by the tracker once its log has started
    return cfg
