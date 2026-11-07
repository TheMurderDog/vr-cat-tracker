"""Cameras whose focus the computer can set (autofocus that can be switched off, and a focus value).

Many webcams have a fixed focus or a ring you turn by hand: nothing here applies to them. Some have autofocus,
which re-focuses whenever something moves close to the camera; that shifts the lens a little, so the lens
calibration no longer fits and tracking drifts. When the driver lets it be switched off (DirectShow's camera
control "Focus", through OpenCV's CAP_PROP_AUTOFOCUS and CAP_PROP_FOCUS), the setup screen finds the best focus
on Board B and saves it as cameras.focus: {<camera key>: value}; every tool that opens a camera then switches
autofocus off and sets that value (capture.camera.Camera.apply_controls, and again after a reconnect).
Experimental: not tried on a real autofocus camera yet. What a driver says can't be trusted on its own: focus-ring
cameras (ELP-style "HD USB Camera") report autofocus as on and accept focus values that move nothing. So the setup
screen only locks a focus after seeing the picture change as it steps the focus; otherwise it says the focus is the
camera's ring. DirectShow reads autofocus back as 1 (on) or 2 (off), others as 1 or 0.
"""

import cv2

# focus ranges seen on UVC webcams: 0-255, 0-250 (in steps of 5), 0-1023, 0-40, ...; the top is found by trying
RANGE_TOPS = (1023, 1000, 800, 511, 500, 255, 250, 200, 127, 120, 100, 60, 50, 40, 30, 20, 10)


def _set(cap, prop, value):
    try:
        ok = bool(cap.set(prop, float(value)))
    except cv2.error:
        ok = False
    try:
        got = float(cap.get(prop))
    except cv2.error:
        got = None
    return ok, got


def probe(cap, find_range=True):
    """What this camera lets the computer do with its focus. Leaves autofocus and focus as they were.
    {"autofocus": 1/0 as it was (None: not reported), "can_turn_off": True/False/None (no autofocus),
     "focus": value now or None, "settable": bool, "range": (lo, hi) or None}"""
    out = {"autofocus": None, "can_turn_off": None, "focus": None, "settable": False, "range": None, "step": 1}
    try:
        af = float(cap.get(cv2.CAP_PROP_AUTOFOCUS))
        fv = float(cap.get(cv2.CAP_PROP_FOCUS))
    except cv2.error:
        return out
    if af in (0.0, 1.0, 2.0):
        out["autofocus"] = 1 if af == 1.0 else 0
    if fv >= 0 and not (fv == 0 and af < 0):
        out["focus"] = fv
    if out["autofocus"] == 1:  # can it be switched off? (and back on: it's left as it was)
        ok, got = _set(cap, cv2.CAP_PROP_AUTOFOCUS, 0)
        out["can_turn_off"] = bool(ok and got is not None and got != 1.0)  # DirectShow reads 2 for off
        if out["can_turn_off"]:
            fv = float(cap.get(cv2.CAP_PROP_FOCUS))
            out["focus"] = fv if fv >= 0 else out["focus"]
    if out["focus"] is not None and out["autofocus"] != 1 or out["can_turn_off"]:
        now = out["focus"]
        test = now + 1 if now is not None and now < 1 else max(0.0, (now or 0) - 1)
        ok, got = _set(cap, cv2.CAP_PROP_FOCUS, test)
        if not (ok and got == test):  # some move only in steps (5): try a bigger one
            test = (now or 0) + 5 if (now or 0) < 5 else (now or 0) - 5
            ok, got = _set(cap, cv2.CAP_PROP_FOCUS, test)
            out["step"] = 5
        out["settable"] = ok and got == test
        if out["settable"] and find_range:
            lo = 0.0 if _set(cap, cv2.CAP_PROP_FOCUS, 0)[1] == 0 else None
            hi = None
            for top in RANGE_TOPS:
                ok, got = _set(cap, cv2.CAP_PROP_FOCUS, top)
                if ok and got == top:
                    hi = float(top)
                    break
            if lo is not None and hi is not None and hi > lo:
                out["range"] = (lo, hi)
        if now is not None:
            _set(cap, cv2.CAP_PROP_FOCUS, now)
    if out["autofocus"] == 1 and out["can_turn_off"]:
        _set(cap, cv2.CAP_PROP_AUTOFOCUS, 1)  # as it was: only a saved focus switches it off for good
    return out


STUCK = "Autofocus can't be turned off: tracking may drift when things move close to the camera"


def describe(info):
    """One plain line for the log, or None for a camera with nothing to control. Only what the driver claims: the
    setup screen's focus lock (k) is what finds out whether the lens really moves."""
    if info["settable"]:
        r = info["range"]
        return "focus can be set by the computer" + (f" ({r[0]:g} to {r[1]:g})" if r else "") + (
            ", autofocus can be switched off" if info["autofocus"] == 1 else "")
    return None


def apply(cap, value):
    """Autofocus off and the focus at value, checked by reading back. (ok, what it reads back)."""
    _set(cap, cv2.CAP_PROP_AUTOFOCUS, 0)
    ok, got = _set(cap, cv2.CAP_PROP_FOCUS, value)
    try:
        af = float(cap.get(cv2.CAP_PROP_AUTOFOCUS))
    except cv2.error:
        af = -1.0
    return bool(ok and got is not None and abs(got - float(value)) < 0.5 and af != 1.0), got


def restore_autofocus(cap):
    """Autofocus back on (after a focus lock that found the lens doesn't move)."""
    return _set(cap, cv2.CAP_PROP_AUTOFOCUS, 1)


def saved(cam_cfg, key):
    """The focus saved for this camera key in cameras.focus, or None."""
    c = cam_cfg["cameras"] if "cameras" in cam_cfg else cam_cfg
    table = c.get("focus") or {}
    value = table.get(key) if isinstance(table, dict) else None
    if value in ("stuck", "ring"):  # found by the setup screen: autofocus won't switch off / its focus is its ring
        return value
    return None if value is None else float(value)


def saved_table(text):
    """cameras.focus from the settings file's text, as [(key, value)] (an empty list when it isn't there)."""
    import yaml
    c = (yaml.safe_load(text) or {}).get("cameras") or {}
    table = c.get("focus") or {}
    return list(table.items()) if isinstance(table, dict) else []


def snap(value, step=1):
    """A focus value the driver accepts: whole numbers, in its steps (some only take multiples of 5)."""
    step = max(1, int(step))
    return int(round(value / step) * step)


def sweep_values(lo, hi, n, step=1):
    """n focus values from lo to hi, evenly, each one the driver accepts."""
    if n < 2:
        return [snap(lo, step)]
    return sorted({min(max(snap(lo + (hi - lo) * i / (n - 1), step), snap(lo, step)), int(hi)) for i in range(n)})
