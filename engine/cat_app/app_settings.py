"""The app's own settings (my_data\\app\\app_settings.json): alerts and buzz, snooze, the room map's heatmap
and auto capture, and the wrist widget. Written by the app, read live by the tracker bridge.

Alert distances and buzz strength are only stored once you change them in the app; until then the
values in settings\\cat_tracker.yaml are used (the bridge reports them to the app).
Needs only the standard library.
"""

import copy
import json
import time
from pathlib import Path

DEFAULTS = {
    "alert": {},                 # overrides of settings/cat_tracker.yaml's alert section, only the keys you changed
    "buzz_style": "once",        # "once": the tracker's own left-right buzz when the warning comes on (as before)
                                 # "rising": both controllers together, light / medium / heavy by how close it
                                 # is, and one step stronger each time it comes closer (each step once)
    "snooze_until": 0.0,         # time.time() until which buzzes are muted (-1: until switched back on)
    "snooze_minutes": 30,        # how long the Snooze button on the main screens mutes it (-1: until switched back on)
    "vr_mode": "d3d11",          # how the SteamVR tab and wrist widget reach SteamVR: "d3d11" (a GPU texture) or "file"
                                 # (a picture file, no graphics card use by the app; for ruling it out when a PC crashes)
    "start_osc": None,           # Start sends to VRChat: the last choice on the desktop window (None: not chosen
                                 # yet, so whatever the SteamVR autostart uses)
    "map": {
        "heat": "wobble",        # "off", "time" (where the cat spends time) or "wobble" (where tracking jitters)
        "trail_wobble": True,    # colour the cat's trail by how much the tracking jitters there
    },
    "auto_capture": {
        "on": False,             # start a training capture by itself while the tracking wobbles
        "wobble_cm": 6.0,        # this much wobble (see the bridge) counts as wobbly
        "max_s": 40.0,           # longest automatic capture
        "max_per_run": 15,       # automatic captures per tracker run at most
    },
    "wrist": {
        "on": False,
        "attach": "left",        # "left" / "right" wrist, "head" (follows your view) or "room" (stays put)
        "show": {"distance": True, "direction": True, "state": True, "snooze": True, "problems": True},
        "fade": True,            # fade out unless you look at it
        "fade_angle": 25.0,      # degrees from the middle of your view where it starts to fade
        "locked": False,         # can't be grabbed (once you have it where you want it)
        "width_m": 0.14,
        "offsets": {},           # where it sits for each attach mode (4x4, set by grabbing it)
    },
}

# what the app's sliders and +/- buttons may set
ALERT_KEYS = {
    "underfoot_m": (0.3, 3.0, "Warn closer than"),
    "radius_m": (0.5, 4.0, "Warn if it's moving within"),
    "buzz_amplitude": (0.1, 1.0, "Buzz strength"),
}
LIMITS = {
    "fade_angle": (10.0, 60.0),
    "width_m": (0.06, 0.40),
    "wobble_cm": (2.0, 20.0),
}
ATTACH = ("left", "right", "head", "room")
HEAT = ("off", "time", "wobble")
BUZZ_STYLES = ("once", "rising")
VR_MODES = ("d3d11", "file")
SNOOZE_MINUTES = (15, 30, 60, 120, -1)


def _num(v, lo, hi, default):
    try:
        return float(min(hi, max(lo, float(v))))
    except (TypeError, ValueError):
        return default


def clamp(s):
    """A full, valid settings dict from whatever was saved."""
    s = s if isinstance(s, dict) else {}
    out = copy.deepcopy(DEFAULTS)
    a = s.get("alert") if isinstance(s.get("alert"), dict) else {}
    for k, (lo, hi, _) in ALERT_KEYS.items():
        if k in a and a[k] is not None:
            out["alert"][k] = _num(a[k], lo, hi, None)
            if out["alert"][k] is None:
                del out["alert"][k]
    if "buzz" in a:
        out["alert"]["buzz"] = bool(a["buzz"])
    if s.get("buzz_style") in BUZZ_STYLES:
        out["buzz_style"] = s["buzz_style"]
    out["snooze_until"] = _num(s.get("snooze_until", 0.0), -1.0, 1e12, 0.0)
    try:
        if int(s.get("snooze_minutes", 30)) in SNOOZE_MINUTES:
            out["snooze_minutes"] = int(s["snooze_minutes"])
    except (TypeError, ValueError, KeyError):
        pass
    if s.get("vr_mode") in VR_MODES:
        out["vr_mode"] = s["vr_mode"]
    if isinstance(s.get("start_osc"), bool):
        out["start_osc"] = s["start_osc"]
    m = s.get("map") if isinstance(s.get("map"), dict) else {}
    if m.get("heat") in HEAT:
        out["map"]["heat"] = m["heat"]
    if "trail_wobble" in m:
        out["map"]["trail_wobble"] = bool(m["trail_wobble"])
    ac = s.get("auto_capture") if isinstance(s.get("auto_capture"), dict) else {}
    out["auto_capture"]["on"] = bool(ac.get("on", False))
    out["auto_capture"]["wobble_cm"] = _num(ac.get("wobble_cm", 6.0), *LIMITS["wobble_cm"], 6.0)
    w = s.get("wrist") if isinstance(s.get("wrist"), dict) else {}
    ow = out["wrist"]
    ow["on"] = bool(w.get("on", False))
    if w.get("attach") in ATTACH:
        ow["attach"] = w["attach"]
    if isinstance(w.get("show"), dict):
        for k in ow["show"]:
            if k in w["show"]:
                ow["show"][k] = bool(w["show"][k])
    ow["fade"] = bool(w.get("fade", True))
    ow["fade_angle"] = _num(w.get("fade_angle", 25.0), *LIMITS["fade_angle"], 25.0)
    ow["locked"] = bool(w.get("locked", False))
    ow["width_m"] = _num(w.get("width_m", 0.14), *LIMITS["width_m"], 0.14)
    if isinstance(w.get("offsets"), dict):
        for k, v in w["offsets"].items():
            try:
                if k in ATTACH and len(v) == 4 and all(len(r) == 4 for r in v):
                    ow["offsets"][k] = [[float(x) for x in r] for r in v]
            except TypeError:
                pass
    return out


def load(path):
    try:
        return clamp(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clamp({})


def save(path, s):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clamp(s), indent=2), encoding="utf-8")
    tmp.replace(path)


def snoozed(s, now=None):
    """True while buzzes are muted."""
    u = s.get("snooze_until", 0.0)
    return u < 0 or u > (time.time() if now is None else now)
