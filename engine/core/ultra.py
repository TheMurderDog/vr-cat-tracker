"""Ultralytics, used without its usage reporting. Import YOLO only through here: `from core.ultra import load_yolo`.

Ultralytics (the YOLO training library) sends anonymous usage events to Ultralytics (Google Analytics) over the
internet while it trains, validates, predicts or exports, when "sync" is on in the user's Ultralytics settings (it is
by default). This project sends nothing anywhere except OSC to this PC (docs/SECURITY.md), so every use here switches
that off first, for this process only: the user's own settings file is left as it is. Downloads Ultralytics needs
(the stock weights on first use, the small model its mixed-precision check loads) still work. (Ultralytics 8.4 has
no other reporting path: Sentry is only mentioned to quiet its logger, and sentry_sdk isn't installed.)

engine/tests/test_ultra_imports.py fails if any other file imports ultralytics directly.
"""


def quiet():
    """Switch off Ultralytics' usage events in this process. Safe to call again. Returns True when they're off."""
    try:
        from ultralytics.utils import events as ev
    except ImportError:  # an Ultralytics without the events module sends nothing
        return True
    ev.events.enabled = False
    return not ev.events.enabled


def load_yolo():
    """The YOLO class, with the usage events already off."""
    quiet()
    from ultralytics import YOLO
    return YOLO
