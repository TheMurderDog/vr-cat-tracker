"""Load config.yaml, the single home for every tunable setting."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"


def load_config(path=None):
    """Return the config as a plain dict. Raises with a clear message if it is missing or malformed."""
    path = Path(path) if path else DEFAULT_CONFIG
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level")
    cfg["_path"] = str(path)
    return cfg


def get(cfg, dotted, default=None):
    """Read a nested value with a dotted key, e.g. get(cfg, "gpu.device_id")."""
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def resolve_path(p):
    """Interpret a config path relative to the repo root unless it is absolute."""
    p = Path(p)
    return p if p.is_absolute() else REPO_ROOT / p
