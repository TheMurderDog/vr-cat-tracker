"""Camera setup screen: see every connected camera live, pick the ones to use, name, order and turn them, and save.

Run from engine/ (1_connect_cameras/1_set_up_cameras.bat does this):  python -m tools.camera_setup [--max-id 9]

The top of the window shows every camera Windows has, live. A camera that can't give the mode in
settings/cameras.yaml (cameras.width/height/fourcc) is shown greyed with the reason, and can't be used.
Devices matching cameras.exclude (VR headset and virtual cameras by default) are listed but never opened.
The bottom shows only the cameras you use, in order, named and turned, laid out exactly like the tracker
window (capture.camera.label_tile / tile_grid): just the names. A camera with a problem (Found.problems: too slow,
damaged frames, heavy compression, flicker, too dark or bright, stuck autofocus) gets a red frame and "Click to
resolve issues"; clicking a tile opens its big view, which lists the problems in plain words with what to do, then
every check (capture.camera.CameraStats, as tools.preview measures them). ? or the ? HELP button: a help window. s writes cameras.ids, names, rotate, devices and
exclude into settings/cameras.yaml, keeping every comment, after copying the old file to my_data/backups.
If no camera works with cameras.backend, the other Windows camera driver is tried, and the one that works
is saved too.

Keys (the selected camera has a yellow border):
  click or 1-9   select a camera        space   use / don't use it
  n              rename it (type, Enter; Esc cancels)
  [ ] or arrows  move it earlier / later in the order
  r              turn it a quarter turn clockwise
  x              exclude it: never open it again (press twice); on an excluded one, include it again
  p              open the selected camera's driver settings (DirectShow)
With the experimental cameras.fps: auto in settings/cat_tracker.yaml, it also checks once per camera whether it
can run at the tracker's lower speed (capture.camera.AUTO_FPS) and says what the tracker will get.
  s              save                   q / Esc quit (asks first if there are unsaved changes)
"""

import argparse
import re
import shutil
import threading
import time

import cv2
import numpy as np
import yaml

from capture.camera import (AUTO_FPS, BACKENDS, BLOCKY_LIMIT, RESCAN_EVERY_S, ROTATIONS, UNPLUG_AFTER_S, unplugged_frame, CameraStats, camera_keys, camera_names, jpeg_blocky, excluded, label_tile,
                            outlined_text, resolve_ids, rotations, spoken, spoken_list, tile_grid)
from capture import focus as camfocus
from capture.devices import list_devices, looks_like_headset
from core.config import DATA, DEFAULT_CONFIG, load_config
from core.runlog import start_run
from core.single import hold_cameras

TURNS = ["none", "cw90", "180", "ccw90"]  # r steps through these, a quarter turn clockwise each
TURN_LABEL = {"none": "upright", "cw90": "turned right", "180": "upside down", "ccw90": "turned left"}
NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,20}$")  # names become file names (intrinsics_<name>.json)
GREEN, GREY, YELLOW, WHITE, RED = (80, 220, 80), (130, 130, 130), (0, 210, 255), (240, 240, 240), (80, 80, 255)
WIN = "Camera setup"
AIM_TIP = ("Aim it so the lower two thirds is floor and the top third shows standing heads. Every spot your cat uses, "
           "and your head when you stand in the middle of the room, should be seen by at least two cameras.")


FOCUS_SWEEP = "Turn the focus ring slowly from one end to the other."
FOCUS_HINT = "To check focus, stand Board B on the floor where your cat walks, facing this camera."
FOCUS_BOARD_FOUND = "Found Board B. Turn the focus ring slowly all the way one way, then back."
FOCUS_ON_TARGET = "Measuring only {what} (the green box): anything else moving in the picture is ignored."
FOCUS_FIND = "Now turn it back until the circle is green."
FOCUS_FOUND = "That's in focus."
FOCUS_LENS = "If you change the focus, redo the lens step for this camera."
FOCUS_STAND = "Stand beside the camera, out of its view, while you turn the ring."
# judging a camera over time, not frame by frame: a person walking past, a light switched on or one burst of
# damaged frames must not turn it red
COVER_HOLD_S = 0.5    # the picker's "cover to find": this long covered before it says which camera it is
LAPTOP_CAMERA = re.compile(r"integrated|facetime|built-?in|front|user.?facing|ir camera|infrared|laptop", re.I)
X_COOLDOWN_S = 1.0    # X held down: after it excluded or included a camera, it waits this long
WARMUP_S = 60.0       # CHECKING: this long watching each camera before it can say CHECKS OK
WINDOW_S = 30.0       # a problem's share is taken over this much of the recent past, sampled once a second
RED_AT = 0.6          # ...red once it's there 60% of that time...
CLEAR_AT = 0.2        # ...and only fine again under 20% (so it can't flicker between the two)
DARK_BELOW = 50.0     # brightness (0-255) under this is too dark: recall 94.8% at 50, 90.6% at 40 (with gain noise)
BRIGHT_ABOVE = 195.0  # over this, too bright: 95.4% recall at 198, 79% at 211 (washed out): a steep edge
# darkness and grain together (the fair test set, grain added and measured with noise_sigma; recall lost against the
# clean 96.4%): brightness 55: grain 2.1 -1.6, 3.15 -3.1, 4.1 -4.9; brightness 70: 2.1 -0.7, 3.15 -1.3, 4.2 -2.5;
# brightness 85: 3.15 -1.0, 4.2 -1.6; brightness 135: 3.15 -0.4, 4.2 -0.4. Dim with little grain: -0.7 at most.
NOISY_AT = 4.0        # sensor noise (grey levels) this high: red, too dark (the test setup's cameras under a dim light: 2.6-3.1)
GRAINY_AT = 2.0       # ...this high while dimmer than DIM_BELOW: yellow note: it runs, more light helps it see the cat
DIM_BELOW = 85.0      # (brightness; above it, grain up to NOISY_AT costs about a point at most)
NOTES = ("dim",)      # lasting findings that are worth saying but don't stop a camera from being used
FLICKER_PROBLEM = 40.0  # light flicker (peak-to-peak %) that counts as a problem: bands up to 70% didn't hurt
NOISE_PART_MAX = 0.6    # sharpness is judged only when sensor noise is at most this share (above, the measure drifts)
FOCUS_SKIP_SHARPNESS = 7.5  # clean_sharpness (a ratio): focused 8.8-19; blur 1 px 4.6-10 (harmless); 1.5 px 2.4-6.1 (never passes)
FOCUS_DROPPED = 0.6   # a camera focused before needs it again when its sharpness falls under 60% of then
TILES = (6, 4)  # the picture is measured in tiles, so something moving in part of it doesn't spoil the rest


def _half(g):
    return cv2.resize(g.astype(np.float32), (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)


def _spread(a, b):
    """The noise (grey levels) in a and b from their difference: its middle half's width (robust: something moving
    in part of the view doesn't count), on floats (on whole grey levels the measure moves in steps of 1)."""
    d = (a - b).ravel()
    q1, q3 = np.percentile(d, [25, 75])
    return float((q3 - q1) / 1.349 / np.sqrt(2))


def noise_sigma(a, b):
    """The sensor's noise at full size (grey levels) from two pictures of the same view a moment apart, measured
    at half size on floats (averaging 4 pixels halves the noise, so it's doubled back)."""
    return 2.0 * _spread(_half(a), _half(b))


def _lap_tiles(g, sigma, tiles=TILES):
    """Per tile: the Laplacian's variance with the noise's share (20 sigma^2) taken out, over brightness squared;
    and the noise's share of it."""
    lap = cv2.Laplacian(g, cv2.CV_32F)
    h, w = g.shape
    nx, ny = tiles
    vals, parts = [], []
    for y in range(ny):
        for x in range(nx):
            sl = (slice(y * h // ny, (y + 1) * h // ny), slice(x * w // nx, (x + 1) * w // nx))
            m2 = max(float(g[sl].mean()) ** 2, 25.0)
            raw = float(lap[sl].var())
            noise = 20 * sigma ** 2
            vals.append(max(raw - noise, 0.0) / m2)
            parts.append(noise / raw if raw > 0 else 1.0)
    return np.array(vals), float(np.median(parts))


def clean_sharpness(gray, prev_gray, tiles=TILES):
    """How sharp the picture is, the same for a plain room and a busy one: fine detail (at half size) against
    coarse detail (at an eighth), per tile, with the sensor noise (measured from two pictures a moment apart) taken
    out of both; x 100. Blur takes away fine detail first; how busy the room is changes both alike. Returns
    (sharpness, or None when noise is too big a part of the fine detail to judge; noise's share).
    Measured (docs/technical/camera_checks.md): focused 9-19, blur 1 px 5-10, 1.5 px 2-6, 2 px 1-4.5."""
    h = (_half(gray), _half(prev_gray))
    e = tuple(cv2.resize(g.astype(np.float32), (g.shape[1] // 8, g.shape[0] // 8), interpolation=cv2.INTER_AREA)
              for g in (gray, prev_gray))
    fine, part = _lap_tiles(h[0], _spread(*h), tiles)
    coarse, _ = _lap_tiles(e[0], _spread(*e), tiles)
    ok = coarse > 1e-3  # tiles with some structure at all (a blank wall says nothing)
    if part > NOISE_PART_MAX or ok.sum() < 6:
        return None, part
    return float(np.median(fine[ok] / coarse[ok]) * 100), part


def sharpness(frame):
    """How sharp the middle of the picture is: the variance of the Laplacian over its centre half."""
    h, w = frame.shape[:2]
    g = frame[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def tile_sharpness(gray, tiles=TILES):
    """Detail in each tile (rows x columns): the Laplacian's variance divided by the tile's brightness squared, so
    auto exposure making the picture brighter or darker doesn't look like focusing (x 1000, for readable numbers)."""
    g = gray.astype(np.float32)
    lap = cv2.Laplacian(g, cv2.CV_32F)
    h, w = gray.shape
    nx, ny = tiles
    out = np.zeros((ny, nx))
    for y in range(ny):
        for x in range(nx):
            sl = (slice(y * h // ny, (y + 1) * h // ny), slice(x * w // nx, (x + 1) * w // nx))
            out[y, x] = 1000.0 * float(lap[sl].var()) / max(float(g[sl].mean()) ** 2, 25.0)
    return out


PREFS = DATA / "setup_prefs.json"  # small choices made on this screen (the focus sound), not settings to share


def load_prefs():
    import json
    try:
        return json.loads(PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(**changes):
    import json
    prefs = dict(load_prefs(), **changes)
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps(prefs, indent=1), encoding="utf-8")
    except OSError:
        pass  # not remembered: harmless


def focus_targets(cfg):
    """What the focus meter looks for: the room marker card (one big marker, readable across the room) and the lens
    board (small markers: found only within about a metre and a half). [(label, detector, ids, pad)]."""
    out = []
    room = (cfg.get("calibration") or {}).get("room") or {}
    if room.get("marker_dictionary"):
        d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, room["marker_dictionary"]))
        out.append(("Board B", cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters()),
                    {int(room.get("marker_id", 7))}, 0.1))
    small = ((cfg.get("calibration") or {}).get("boards") or {}).get("small")
    if small:
        d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, small["dictionary"]))
        first = int(small["first_marker_id"])
        n = small["squares"][0] * small["squares"][1] // 2
        out.append(("Board A", cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters()),
                    set(range(first, first + n)), 0.25))
    return out


def find_target(gray, targets):
    """(label, (x, y, w, h)) of the first target in the picture, padded a little, or None."""
    H, W = gray.shape
    for label, det, ids, pad in targets:
        corners, found, _ = det.detectMarkers(gray)
        if found is None:
            continue
        pts = [c.reshape(-1, 2) for c, i in zip(corners, found.ravel()) if int(i) in ids]
        if not pts:
            continue
        pts = np.concatenate(pts)
        (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
        px, py = pad * (x1 - x0), pad * (y1 - y0)
        x0, y0 = max(0, int(x0 - px)), max(0, int(y0 - py))
        x1, y1 = min(W, int(np.ceil(x1 + px))), min(H, int(np.ceil(y1 + py)))
        if x1 - x0 >= 18 and y1 - y0 >= 18:
            return label, (x0, y0, x1 - x0, y1 - y0)
    return None


def moved(a, b):
    """Two target boxes: was the card moved closer or further (its size changed), so the range must start over? A
    shift alone is the camera wobbling, or the card slid along at the same distance: the box just follows it."""
    (_, _, aw, ah), (_, _, bw, bh) = a, b
    return not 0.6 < (bw * bh) / max(aw * ah, 1) < 1.67


def follow(prev, cur, rect, margin):
    """How far the picture around the card moved between two frames (phase correlation: works while it's too
    blurry to recognise). (dx, dy) in pixels, or (0, 0) when it can't tell."""
    x, y, w, h = rect
    H, W = cur.shape
    x0, y0, x1, y1 = max(0, x - margin), max(0, y - margin), min(W, x + w + margin), min(H, y + h + margin)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return 0, 0
    a, b = prev[y0:y1, x0:x1].astype(np.float32), cur[y0:y1, x0:x1].astype(np.float32)
    win = cv2.createHanningWindow((x1 - x0, y1 - y0), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, win)
    if response < 0.05 or abs(dx) > margin or abs(dy) > margin:
        return 0, 0
    return int(round(dx)), int(round(dy))


def focus_colour(t):
    """Red (0) through yellow (0.5) to green (1), BGR."""
    t = min(max(t, 0.0), 1.0)
    return (0, int(255 * min(1, 2 * t)), int(255 * min(1, 2 * (1 - t))))


class FocusMeter:
    """A focus meter that needs no restart, and copes with someone in the picture.

    The picture is measured in tiles (each tile's detail relative to its brightness, so auto exposure doesn't move
    it; tiles where something moves keep their last value; each tile held over about half a second, so a one-frame
    spike never counts). Each tile is compared with its own best over the last window_s, giving 0 to 1, and the
    middle tile (median) is the reading: at the sharp point most tiles are at their best wherever a person stands,
    as long as they cover less than half the picture. An old best fades out on its own after window_s. Colour and
    level only show once the tiles have a real spread over that window (the ring turned end to end). The bar's line
    is the best reading lately, falling slowly, like an audio level meter: get the bar up to the line."""

    def __init__(self, smooth=0.35, green_at=0.85, hold_s=0.7, change=20.0, window_s=25.0, spread=2.0,
                 peak_decay_s=0.03, steady_n=15, targets=(), look_every_s=0.1, forget_target_s=60.0, background=False,
                 card_n=3, card_smooth=0.7):
        # green_at: an aid, not perfection. The card's spot is the sharpest the room gets anyway, so near the best
        # (85% of the way from the blurriest to the sharpest lately) is good enough, held for under a second
        # (calibration.focus_in_focus_at and focus_hold_s in settings/cameras.yaml).
        self.smooth, self.green_at, self.hold_s, self.change = smooth, green_at, hold_s, change
        self.window_s, self.spread, self.peak_decay_s, self.steady_n = window_s, spread, peak_decay_s, steady_n
        # targets (focus_targets): with the marker card or lens board in view only its area is measured. It stops
        # being recognised at the blurry end of the ring, so its area is kept while it isn't found (the card isn't
        # moving, only the focus); found closer or further means it was moved: the range starts over.
        # On the card nothing else moves, so it reacts quickly there: a 3-frame median (no one-frame spikes), light
        # smoothing, no "hold while it moves" (that held it still whenever the camera wobbled as the ring was turned);
        # the box follows the card instead. The stricter protections stay for the whole picture, where people walk.
        self.targets, self.look_every_s, self.forget_target_s = list(targets), look_every_s, forget_target_s
        self.background, self.card_n, self.card_smooth = background, card_n, card_smooth
        self._busy, self._result = False, None  # background marker search: running, and its answer
        self.events = []
        self.reset()

    def reset(self, keep_target=False):
        if not keep_target:
            self.rect = None        # (x, y, w, h) in the raw picture: the target's area, or None (the whole picture)
            self.target = None      # its label ("Board B": the marker card, "Board A": the checkerboard)
            self.target_seen = None
            self.last_look = None
            self.prev_gray = None
        self.value = self.lo = self.peak = None
        self.hi = 1.0
        self.tiles = self.small = None
        self.recent = []         # the last steady_n tile readings (each tile held over half a second)
        self.history = []        # (time, held tiles, reading) over the last window_s
        self.tile_spread = 1.0   # how much the tiles' detail has changed lately (max / min, middle tile)
        self.green_since = None
        self.green_last = 0.0
        self.announced = False
        self.told_find = False
        self.last_t = None

    @property
    def phase(self):
        if not self.ranged():
            return "learn"
        return "found" if self.announced else "find"

    def ranged(self):
        return self.value is not None and self.tile_spread >= self.spread

    def level(self):
        """0 (the blurriest lately) to 1 (the sharpest lately), or None until the ring has been turned end to end."""
        if not self.ranged() or self.lo is None or self.lo >= 1:
            return None
        return min(max((self.value - self.lo) / (1.0 - self.lo), 0.0), 1.0)

    def green(self):
        t = self.level()
        return t is not None and t >= self.green_at

    def update(self, frame, now=None):
        now = time.monotonic() if now is None else now
        dt = 0.0 if self.last_t is None else max(0.0, now - self.last_t)
        self.last_t = now
        full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        self.look(full, now)
        if self.rect is not None and self.prev_gray is not None and self.prev_gray.shape == full.shape:
            x, y, w, h = self.rect  # the camera wobbled: the box moves with the picture
            dx, dy = follow(self.prev_gray, full, self.rect, max(24, max(w, h) // 2))
            H, W = full.shape
            self.rect = (min(max(x + dx, 0), W - w), min(max(y + dy, 0), H - h), w, h)
        self.prev_gray = full if self.rect is not None else None
        card = self.rect is not None
        if card:
            x, y, w, h = self.rect
            gray = full[y:y + h, x:x + w]
            nx, ny = 1, 1
        else:
            gray, (nx, ny) = full, TILES
        small = cv2.resize(gray, (nx * 16, ny * 16), interpolation=cv2.INTER_AREA).astype(np.float32)
        sharp = tile_sharpness(gray, (nx, ny))
        if self.tiles is None:
            self.tiles = sharp
        elif card:
            self.tiles = self.tiles + self.card_smooth * (sharp - self.tiles)
        else:  # tiles where something moves keep their last value
            cells = np.abs(small - self.small).reshape(ny, 16, nx, 16).transpose(0, 2, 1, 3).reshape(ny, nx, 256)
            steady = np.percentile(cells, 95, axis=2) < self.change
            self.tiles = np.where(steady, self.tiles + self.smooth * (sharp - self.tiles), self.tiles)
        self.small = small
        self.recent = (self.recent + [self.tiles.copy()])[-(self.card_n if card else self.steady_n):]
        held = np.median(np.stack(self.recent), axis=0)  # each tile over half a second: no one-frame spike
        self.history = [h for h in self.history if now - h[0] <= self.window_s]
        stack = np.stack([h[1] for h in self.history] + [held])
        best, least = stack.max(axis=0), stack.min(axis=0)
        self.value = float(np.median(held / np.maximum(best, 1e-6)))  # each tile against its own best lately
        self.tile_spread = float(np.median(best / np.maximum(least, 1e-6)))
        self.history.append((now, held, self.value))
        self.lo = min(h[2] for h in self.history)
        self.peak = self.value if self.peak is None else max(self.value, self.peak * (1 - self.peak_decay_s) ** dt)
        if self.ranged() and not self.told_find:
            self.told_find = True
            self.events.append(FOCUS_FIND)
        if self.green():
            self.green_since = self.green_since or now
            self.green_last = now
            if not self.announced and now - self.green_since >= self.hold_s:
                self.announced = True
                self.events.append(FOCUS_FOUND)
        else:
            if now - self.green_last > 0.4:  # a short flicker doesn't break the hold
                self.green_since = None
            if self.announced and (self.level() or 0) < self.green_at - 0.25:
                self.announced = False  # turned well away: say it again when it's found again
        return self.value

    def look(self, gray, now):
        """A few times a second: is the marker card or lens board in view, and where?"""
        if self._result is not None:  # the background search finished
            got, self._result = self._result, None
            self.apply_look(got[0], got[1])
        if not self.targets or self._busy or (self.last_look is not None and now - self.last_look < self.look_every_s):
            return
        self.last_look = now
        if not self.background:
            self.apply_look(find_target(gray, self.targets), now)
            return
        self._busy = True
        img = gray.copy()

        def run():
            try:
                self._result = (find_target(img, self.targets), now)
            finally:
                self._busy = False
        threading.Thread(target=run, name="focus target", daemon=True).start()

    def apply_look(self, hit, now):
        if hit is None:
            if self.rect is not None and now - self.target_seen > self.forget_target_s:
                self.reset()  # it's gone (not just blurry for a moment): back to the whole picture
                self.events.append("target lost")
            return
        label, rect = hit
        if self.rect is None or label != self.target or moved(self.rect, rect):
            first = self.rect is None
            self.reset()
            self.rect, self.target = rect, label
            self.events.append(f"target {'found' if first else 'moved'}: {label}")
        else:  # the same card, the same size: the box goes where it was found (following can drift a little)
            self.rect = rect[:2] + self.rect[2:]
        self.target_seen = now

    def instruction(self):
        return {"learn": FOCUS_SWEEP, "find": FOCUS_FIND, "found": FOCUS_FOUND}[self.phase]

    def tips(self):
        where = FOCUS_ON_TARGET.format(what=self.target) if self.rect is not None else FOCUS_HINT if self.targets else ""
        return [self.instruction(), where, FOCUS_STAND, FOCUS_LENS, "b: start over."]

    def panel(self, width, height):
        """The circle (readable from across the room), the bar with its peak line, and the tips, on a dark panel."""
        img = np.full((height, width, 3), 30, np.uint8)
        r = int(min(width * 0.42, height * 0.26))
        c = (width // 2, int(height * 0.3))
        t = self.level()
        colour = (90, 90, 90) if t is None else focus_colour(t / self.green_at)
        cv2.circle(img, c, r, colour, -1, cv2.LINE_AA)
        cv2.circle(img, c, r, (230, 230, 230), 3, cv2.LINE_AA)
        word = "IN FOCUS" if self.green() else "TURN THE RING" if t is None else f"{int(round(100 * t))}%"
        scale = 1.4 if len(word) < 10 else 0.9
        size = cv2.getTextSize(word, cv2.FONT_HERSHEY_SIMPLEX, scale, 3)[0]
        outlined_text(img, word, (c[0] - size[0] // 2, c[1] + r + 50), cv2.FONT_HERSHEY_SIMPLEX, scale, WHITE, 3,
                      cv2.LINE_AA)
        # the bar: the reading now (fill) against the best lately (white line, falling slowly)
        y0, y1, x0, x1 = c[1] + r + 75, c[1] + r + 125, 14, width - 14
        cv2.rectangle(img, (x0, y0), (x1, y1), (70, 70, 70), 2)
        if self.value is not None:
            fill = int((x1 - x0) * min(self.value, 1))
            cv2.rectangle(img, (x0 + 2, y0 + 2), (x0 + max(fill, 2), y1 - 2), colour if t is not None else (160, 160, 160), -1)
            xp = x0 + int((x1 - x0) * min(self.peak or 0, 1))
            cv2.line(img, (xp, y0 - 8), (xp, y1 + 8), WHITE, 4)
        y = y1 + 40
        for line in _wrap(" ".join(t for t in self.tips() if t), width - 24, 0.6):
            outlined_text(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1, cv2.LINE_AA)
            y += 26
        return img


def _wrap(text, width, scale):
    lines, line = [], ""
    for word in text.split(" "):
        test = (line + " " + word) if line else word
        if line and cv2.getTextSize(test, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > width:
            lines.append(line)
            line = word
        else:
            line = test
    return lines + [line]


def screen_size():
    try:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:  # noqa: BLE001  (not Windows)
        return 1920, 1080
KEY_LEFT, KEY_RIGHT = 2424832, 2555904  # cv2.waitKeyEx arrow codes on Windows


class Found:
    """One camera device: its live picture (or last picture), and whether it can be used.
    An excluded device is never opened."""

    def __init__(self, device_id, c, name="camera", path=None, exclude=False):
        self.id, self.name, self.path = device_id, name, path
        self.c = c
        self.tracker_fps = None  # what it really gives when asked for AUTO_FPS, once speed_check has run
        self.excluded = exclude
        self.cap = None
        self.frame = None
        self.reason = None
        self.got = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.stats = CameraStats(c["fps"], int(c.get("flicker_window_frames", 90)))
        self.target_fps = c["fps"]
        self.want_settings = False  # p: open the driver's settings dialog, from the capture thread
        self.focus_info = None      # what its focus allows (capture.focus.probe), once opened
        self.focus_value = getattr(self, "focus_value", None)  # a locked focus: set again whenever it (re)opens
        self.focus_jobs = []        # focus values to set, from the capture thread
        self.focus_verdict = getattr(self, "focus_verdict", None)  # after k: "locked", "ring" (no effect), "stuck"
        if exclude:
            return
        self.device_index = device_id  # Windows' number for it now (self.id stays the same: the screen's handle)
        import collections
        self.quality = collections.deque(maxlen=240)  # blockiness of recent good frames (about 2 s)
        self.state = "ok"               # or "unplugged": waiting to come back (Setup.rescan reopens it)
        hold_cameras()  # wait while another tool still has the cameras
        self._start_capture()

    def _start_capture(self):
        """Open it in the configured mode and start the live picture; sets self.reason if it can't be used."""
        c = self.c
        self.reason = None
        self.cap = cv2.VideoCapture(self.device_index, BACKENDS[c.get("backend", "any")])
        if not self.cap.isOpened():
            self.cap = None
            self.reason = "doesn't open (is another program using it?)"
            return
        cap = self.cap
        # same order as capture.camera.Camera.open: FOURCC first, or DirectShow may pick a slow uncompressed mode
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.get("fourcc", "MJPG")))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        fourcc = "".join(chr((fcc >> 8 * i) & 0xFF) for i in range(4)) if fcc > 0 else "?"
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.got = f"{w}x{h} {fourcc}"
        if not ok or frame is None:
            self.reason = "opened, but sends no picture"
        elif (w, h) != (c["width"], c["height"]) or (c.get("require_exact_mode", True) and fourcc != c.get("fourcc", "MJPG")):
            self.reason = mode_problem(cap, c, self.got)
        self.frame = frame
        if self.reason:
            cap.release()  # keep its one picture, so you can see what it is, but don't hold the device
            self.cap = None
        else:
            try:
                self.focus_info = camfocus.probe(cap)
                if self.focus_value is not None and self.focus_info["settable"]:
                    camfocus.apply(cap, self.focus_value)
            except Exception:  # noqa: BLE001  (a driver that misbehaves here just has no focus control)
                self.focus_info = None
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def unplug(self):
        """It stopped sending pictures: release the device and show that it's waiting (called on its own thread)."""
        self.state = "unplugged"
        self.restart_checks()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:  # noqa: BLE001
                pass
            self.cap = None
        c = self.c
        with self._lock:
            self.frame = unplugged_frame(int(c["width"]), int(c["height"]), self.name if self.name != "camera" else "camera")

    def reopen(self, device_index, path):
        """Back (on the same USB port, or a new one): open it again. Returns True if it gives its picture."""
        self.restart_checks()
        self.last_new = None
        self.device_index, self.path = device_index, path
        self._start_capture()
        if self.reason is None:
            self.state = "ok"
            return True
        return False

    @property
    def usable(self):
        return self.reason is None and not self.excluded

    @property
    def nothing(self):
        """Nothing at this id at all (only when scanning ids without a device list)."""
        return self.cap is None and self.frame is None and not self.excluded and self.reason.startswith("doesn't")

    def _run(self):
        prev = None
        last_new = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - last_new > UNPLUG_AFTER_S:  # no new picture for a while: unplugged
                self.unplug()
                return
            if self.want_settings:
                self.want_settings = False
                self.cap.set(cv2.CAP_PROP_SETTINGS, 1)
            if self.focus_jobs:
                with self._lock:
                    jobs, self.focus_jobs = self.focus_jobs, []
                for value in jobs[-1:]:  # only the newest matters
                    self.focus_ok = camfocus.apply(self.cap, value)
            ok, frame = self.cap.read()
            t_ns = time.perf_counter_ns()
            if not ok or frame is None:
                self.stats.read_failures += 1
                time.sleep(0.02)
                continue
            sig = frame[::24, ::24].tobytes()  # the backend handing back its old buffer is not a new frame
            if sig == prev:
                self.stats.duplicates += 1
                continue
            prev = sig
            last_new = self.last_new = time.monotonic()
            b = jpeg_blocky(frame)
            if b > BLOCKY_LIMIT:  # damaged on the way (USB): counted, never shown or measured
                self.stats.broken += 1
                continue
            self.quality.append(b)  # the picture quality line: the camera's own compression
            small = cv2.resize(frame, (32, 24), interpolation=cv2.INTER_AREA)
            self.stats.on_frame(t_ns, cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            with self._lock:
                self.frame = frame

    def checks(self):
        """[(text, colour)] for the bottom view: speed, dropped frames, flicker and brightness, coloured like the
        preview's (green fine, yellow look at it, red fix it)."""
        st = self.stats
        fps, flick, target = st.fps(), st.flicker_pct(), self.target_fps
        if fps < 0.97 * target:
            speed = (f"{fps:.0f} of {target} fps  TOO SLOW", RED)
        else:  # many cameras offer only their top speed at a size (e.g. 120 fps at 1280x720) and ignore the asked
            # one; that's fine, the tracker takes the newest frame. Windows decodes every frame either way.
            speed = (f"{fps:.0f} fps" + (" (the camera's own speed: fine)" if fps > 1.2 * target else ""), GREEN)
        drops = (f"dropped {st.dropped}", GREEN if st.dropped == 0 and not st.read_failures else YELLOW)
        if flick is None:
            light = ("light flicker: measuring", WHITE)
        elif flick < 1:
            light = (f"no light flicker ({flick:.1f}%)", GREEN)
        elif flick < FLICKER_PROBLEM:
            light = (f"light flicker {flick:.1f}% (harmless for tracking)", GREEN)
        else:
            light = (f"STRONG LIGHT FLICKER {flick:.0f}%: set a fixed exposure", RED)
        b = st.brightness()
        bright = (f"brightness {b:.0f}/255" + ("  TOO DARK" if b < DARK_BELOW else "  TOO BRIGHT" if b > BRIGHT_ABOVE
                                                else ""), WHITE if DARK_BELOW <= b <= BRIGHT_ABOVE else RED)
        grain = getattr(self, "noise", None)
        if DARK_BELOW <= b < DIM_BELOW and grain is not None and GRAINY_AT <= grain < NOISY_AT:
            bright = (f"brightness {b:.0f}/255, grain {grain:.1f}: a bit dark", YELLOW)
        seen = st.frames + st.broken
        share = 100.0 * st.broken / seen if seen else 0.0
        damaged = (f"damaged frames {share:.1f}%" + (": move it to a USB port on another controller, not a shared hub"
                                                     if share >= 1 else ""), GREEN if share < 1 else YELLOW if share < 5 else RED)
        recent = getattr(self, "quality", ())
        q = float(np.median(recent)) if len(recent) >= 20 else None
        if q is None:
            quality = ("picture quality: checking", WHITE)
        elif q < QUALITY_YELLOW:
            quality = (f"picture quality good ({q:.2f})", GREEN)
        else:
            tip = ("move it to a USB port on another controller" if share >= 1 else "press m to test its other modes")
            quality = (f"{'some' if q < QUALITY_RED else 'HEAVY'} compression ({q:.2f}): {tip}",
                       YELLOW if q < QUALITY_RED else RED)
        out = [speed, drops, damaged, quality, light, bright]
        fi = getattr(self, "focus_info", None)
        verdict, locked = getattr(self, "focus_verdict", None), getattr(self, "focus_value", None)
        if verdict == "stuck":
            out.append((camfocus.STUCK, RED))
        elif locked is not None:
            out.append((f"focus locked at {locked:g} (experimental)", GREEN))
        elif fi and fi["settable"] and verdict != "ring":
            out.append(("focus may be settable by the computer: k in its big view (experimental)", WHITE))
        return out

    def problems_now(self, broken_share):
        """{key: (what's wrong, what to do)} right now; broken_share: the share of damaged pictures in the last
        second. Only real problems: a few dropped frames or under 1% damaged ones are normal and don't count."""
        st, out = self.stats, {}
        fps, target = st.fps(), self.target_fps
        if fps < 0.97 * target:
            out["slow"] = (f"Too slow: {fps:.0f} of {target} frames a second",
                           "Move it to a USB port on another controller (not a hub shared with another camera).")
        if broken_share >= 0.01:
            out["damaged"] = (f"Damaged pictures ({100 * broken_share:.1f}% lately)",
                              "Not enough USB bandwidth: use a USB port on another controller, not a shared hub.")
        recent = getattr(self, "quality", ())
        if len(recent) >= 20 and float(np.median(recent)) >= QUALITY_YELLOW:
            out["blocky"] = ("Blurry, blocky pictures (heavy compression)", "Press M in this view to test its other modes.")
        flick = st.flicker_pct()
        if flick is not None and flick >= FLICKER_PROBLEM:
            out["flicker"] = (f"The room light flickers strongly in its picture ({flick:.0f}%)",
                              "Set a fixed exposure (cameras.exposure_ms in settings), or use other lights.")
        b = st.brightness()
        if b < DARK_BELOW:
            out["dark"] = ("Too dark", "Turn on a light or open a curtain.")
        elif getattr(self, "noise", 0) >= NOISY_AT:  # bright enough on average, but the camera's gain is way up
            out["dark"] = ("Too dark: the picture is grainy", "Turn on a light or open a curtain.")
        elif b > BRIGHT_ABOVE:
            out["bright"] = ("Too bright", "Close a curtain, or turn it away from a lamp or window.")
        elif b < DIM_BELOW and getattr(self, "noise", 0) >= GRAINY_AT:
            out["dim"] = ("A bit dark and grainy", "It still runs, but more light helps it see the cat.")
        if getattr(self, "focus_verdict", None) == "stuck":
            out["stuck"] = ("Autofocus stuck on", camfocus.STUCK)
        return out

    def sample(self, now=None):
        """Once a second (called from the screen's drawing): what's wrong now, and how sharp it is. The verdicts
        (problems, checking, sharp) come from these samples, never from one frame."""
        now = time.monotonic() if now is None else now
        if not self.usable or now - getattr(self, "_last_sample", -9) < 1.0:
            return
        if not self.connected:  # nothing new coming in: the watching starts over once it is
            self.restart_checks()
            self._last_sample = now
            return
        if not hasattr(self, "samples"):
            self.samples, self.raised, self.sharps = [], {}, []
            self.watch_since, self._counts = now, (self.stats.frames, self.stats.broken)
        self._last_sample = now
        frames, broken = self.stats.frames, self.stats.broken
        df, db = frames - self._counts[0], broken - self._counts[1]
        self._counts = (frames, broken)
        if df + db == 0:  # nothing arrived in the last second
            return
        frame = self.latest()
        g = prev = None
        if frame is not None:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            prev = getattr(self, "_prev_gray", None)
            self._prev_gray = g
            if prev is not None and prev.shape == g.shape:
                self.noise = noise_sigma(g, prev)  # the sensor's noise: high when the camera's gain is up (dim)
        self.samples.append((now, self.problems_now(db / (df + db))))
        self.samples = [s for s in self.samples if now - s[0] <= WINDOW_S]
        if g is not None:
            if prev is not None and prev.shape == g.shape:
                s, noise_part = clean_sharpness(g, prev)
                # judged only when the sensor noise is a small part of it (dim rooms: the camera's gain adds
                # noise, which looks just like detail to the measure)
                self.noise_part = noise_part
                if s is not None:
                    self.sharps = (self.sharps + [s])[-15:]
        n = len(self.samples)
        for key in {k for _, p in self.samples for k in p} | set(self.raised):
            share = sum(1 for _, p in self.samples if key in p) / n
            if key in self.raised and share < CLEAR_AT:
                del self.raised[key]
            elif share >= RED_AT and n >= 10:
                self.raised[key] = next(p[key] for _, p in reversed(self.samples) if key in p)

    def restart_checks(self):
        """Forget what was watched: it starts CHECKING again (unplugged, back, or its pictures stopped)."""
        for a in ("samples", "raised", "sharps", "watch_since", "_counts", "_last_sample"):
            if hasattr(self, a):
                delattr(self, a)

    @property
    def connected(self):
        """Sending new pictures: not unplugged, and the last new one under 2 s ago."""
        if getattr(self, "state", "ok") == "unplugged":
            return False
        last = getattr(self, "last_new", None)
        return last is None or time.monotonic() - last < 2.0

    def problems(self):
        """[(what's wrong, what to do)]: the problems that have lasted (sample), in plain words."""
        if not self.usable:
            return [(f"Can't be used: {self.reason}", "Try another USB port, or leave it out (X).")]
        if not self.connected:
            return [("Not connected: no new pictures", "Plug it back in (or check its cable): it reconnects by "
                                                         "itself, then it's checked again.")]
        return [v for k, v in getattr(self, "raised", {}).items() if k not in NOTES]

    def notes(self):
        """[(what, what to do)]: lasting findings that don't stop it being used (yellow, not red)."""
        if not self.usable or not self.connected:
            return []
        return [v for k, v in getattr(self, "raised", {}).items() if k in NOTES]

    def checking_left(self, now=None):
        """Seconds of watching left before it can say CHECKS OK (WARMUP_S in all)."""
        now = time.monotonic() if now is None else now
        since = getattr(self, "watch_since", None)
        return WARMUP_S if since is None else max(0.0, WARMUP_S - (now - since))

    def sharp(self):
        """How sharp its picture is lately (the median of tile_sharpness, over the last 15 s), or None."""
        s = getattr(self, "sharps", [])
        return float(np.median(s)) if len(s) >= 3 else None

    @property
    def focus_settable(self):
        fi = getattr(self, "focus_info", None)
        return bool(fi and fi["settable"])

    def set_focus(self, value):
        """Set its focus (autofocus off) from the capture thread."""
        with self._lock:
            self.focus_jobs.append(float(value))

    def latest(self):
        with self._lock:
            return self.frame

    def speed_check(self, fps=AUTO_FPS, seconds=1.0):
        """How fast it really runs when asked for fps (drivers often ignore the speed asked for): closes the live
        picture, measures with a fresh open, then opens the live picture again as before. Nothing is stored in the
        camera; the tracker asks for its own speed whenever it starts."""
        c, keep = self.c, self.tracker_fps
        self.close()
        hold_cameras()
        cap = cv2.VideoCapture(self.device_index, BACKENDS[c.get("backend", "any")])
        real = None
        try:
            for prop, v in ((cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.get("fourcc", "MJPG"))),
                            (cv2.CAP_PROP_FRAME_WIDTH, c["width"]), (cv2.CAP_PROP_FRAME_HEIGHT, c["height"]),
                            (cv2.CAP_PROP_FPS, fps)):
                cap.set(prop, v)
            if cap.isOpened() and cap.read()[0]:
                prev, n, t0 = None, 0, time.perf_counter()
                while time.perf_counter() - t0 < seconds:
                    ok, f = cap.read()
                    if ok:
                        sig = f[::24, ::24].tobytes()
                        n += sig != prev
                        prev = sig
                real = n / (time.perf_counter() - t0)
        finally:
            cap.release()
        handle = self.id
        Found.__init__(self, device_index_now(self), c, self.name, self.path)  # the live picture again, as before
        self.id = handle
        self.tracker_fps = real if real else keep
        return real

    def tracker_line(self):
        """What the tracker will get from this camera, for the bottom view."""
        if self.tracker_fps is None:
            return ("tracker speed: checking ...", WHITE)
        if self.tracker_fps <= 1.15 * AUTO_FPS:
            return (f"tracker will run it at {AUTO_FPS} fps (saves CPU)", GREEN)
        return (f"can't run slower: tracker uses {self.tracker_fps:.0f} fps (fine, more CPU)", WHITE)

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
            self._thread = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def scan(c, max_id, log, devices=None, misses_to_stop=4):
    """Every camera to show. With Windows' device list (devices: [(name, path)] in DirectShow order), every device
    is listed and the excluded ones aren't opened. Without it, ids from 0 up are tried until max_id, or until
    misses_to_stop ids in a row don't open."""
    found = []
    if devices is not None:
        for i, (name, path) in enumerate(devices):
            skip = excluded(c, name, path)
            f = Found(i, c, name, path, exclude=skip)
            if f.usable or skip:  # fine (or left out on purpose): only the log needs it
                log.debug("id %d (%s): %s", i, name, "excluded, not opened" if skip else "OK, " + f.got)
            else:
                log.info("  %s (id %d) can't be used: %s", name, i, f.reason)
            found.append(f)
            if not skip:
                time.sleep(float(c.get("open_delay_s", 0.5)))
        return found
    misses = 0
    for i in range(max_id + 1):
        f = Found(i, c)
        if f.nothing:
            log.info("id %d: nothing", i)
            misses += 1
            if misses >= misses_to_stop:
                break
            continue
        misses = 0
        if f.usable:
            log.debug("id %d: OK, %s", i, f.got)
        else:
            log.info("  camera id %d can't be used: %s", i, f.reason)
        found.append(f)
        time.sleep(float(c.get("open_delay_s", 0.5)))
    return found


# ---- settings file ---------------------------------------------------------------------------------------------

FOCUS_COMMENT = "set by the setup screen (k): autofocus off and this focus, per camera key"


def logging_info(*a):
    import logging
    logging.getLogger("camera_setup").info(*a)


def _flow(values):
    return "[" + ", ".join(str(v) for v in values) + "]"


def _quote(s):
    return "'" + str(s).replace("'", "''") + "'"  # YAML single quotes: backslashes and # are kept as they are


def _section(text):
    start = re.search(r"(?m)^cameras:[^\n]*\n", text)
    if not start:
        raise ValueError("no cameras: section in the settings file")
    end = re.search(r"(?m)^\S", text[start.end():])
    return start.end(), start.end() + (end.start() if end else len(text) - start.end())


def _set_key(text, key, value):
    """Replace the value of `  key:` in the cameras section, keeping its comment where it was."""
    a, b = _section(text)
    body = text[a:b]
    m = re.search(rf"(?m)^(  {key}:)([ \t]*)([^#\n]*?)([ \t]*)(#[^\n]*)?$", body)
    if not m:
        raise ValueError(f"no cameras.{key} line in the settings file")
    line = f"{m.group(1)} {value}"
    if m.group(5):
        col = m.start(5) - m.start(1)  # keep the comment in its column when the new value fits
        line = line.ljust(col) if len(line) < col else line + "  "
        line += m.group(5)
    body = body[:m.start()] + line + body[m.end():]
    return text[:a] + body + text[b:]


def _set_list(text, key, items, comment):
    """Write `  key:` in the cameras section as a block list (one `    - 'item'` per line), keeping its comment.
    Adds the key after cameras.names when the file doesn't have it yet (settings from before it existed)."""
    a, b = _section(text)
    body = text[a:b]
    m = re.search(rf"(?m)^  {key}:[^\n]*\n(?:    - [^\n]*\n|[ \t]*#[^\n]*\n(?=    - ))*", body)
    if m:
        old = re.match(rf"  {key}:[^#\n]*(#[^\n]*)?", m.group(0))
        comment = old.group(1) or ("# " + comment)
        at, end = m.start(), m.end()
    else:
        names = re.search(r"(?m)^  names:[^\n]*\n", body)
        if not names:
            raise ValueError("no cameras.names line in the settings file")
        at = end = names.end()
        comment = "# " + comment
    head = f"  {key}: []" if not items else f"  {key}:"
    block = head.ljust(28) + comment + "\n" + "".join(f"    - {_quote(i)}\n" for i in items)
    body = body[:at] + block + body[end:]
    return text[:a] + body + text[b:]


DEVICES_COMMENT = "each camera's USB device, set by the setup screen: finds it again if its id changes"
EXCLUDE_COMMENT = "devices never opened: part of a name or device path (VR headset and virtual cameras)"


KEYS_COMMENT = "what each camera's calibration is filed under: stays the same when you rename it (don't edit)"


def _set_or_add_key(text, key, value, comment):
    """_set_key, or add `  key: value  # comment` after cameras.names when the file doesn't have it yet."""
    try:
        return _set_key(text, key, value)
    except ValueError:
        a, b = _section(text)
        body = text[a:b]
        names = re.search(r"(?m)^  names:[^\n]*\n", body)
        if not names:
            raise
        line = f"  {key}: {value}".ljust(28) + "  # " + comment + "\n"
        return text[:a] + body[:names.end()] + line + body[names.end():] + text[b:]


def save_settings(path, ids, names, turns, backup_dir, backend=None, devices=None, exclude=None, keys=None):
    """Write cameras.ids, cameras.names and cameras.rotate (and cameras.backend, cameras.devices, cameras.exclude and
    cameras.keys, if given) into the settings file, keeping everything else. The old file is copied to backup_dir
    first. Returns the backup's path."""
    text = path.read_text(encoding="utf-8")
    new = _set_key(text, "ids", _flow(ids))
    new = _set_key(new, "names", _flow(names))
    if keys is not None:
        new = _set_or_add_key(new, "keys", _flow(keys), KEYS_COMMENT)
    new = _set_key(new, "rotate", turns[0] if len(set(turns)) == 1 else _flow(turns))
    if backend:
        new = _set_key(new, "backend", backend)
    if devices is not None:
        new = _set_list(new, "devices", devices, DEVICES_COMMENT)
    if exclude is not None:
        new = _set_list(new, "exclude", exclude, EXCLUDE_COMMENT)
    check = yaml.safe_load(new)["cameras"]  # never write a file that doesn't read back as what was asked for
    if (check["ids"] != list(ids) or [str(n) for n in check["names"]] != list(names)
            or rotations({"cameras": check}) != list(turns) or (backend and check["backend"] != backend)
            or (devices is not None and (check.get("devices") or []) != list(devices))
            or (exclude is not None and (check.get("exclude") or []) != list(exclude))
            or (keys is not None and [str(k) for k in (check.get("keys") or [])] != list(keys))):
        raise ValueError("the settings file didn't read back as expected; nothing was saved")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"cameras_{time.strftime('%Y%m%d-%H%M%S')}.yaml"
    shutil.copy2(path, backup)
    path.write_text(new, encoding="utf-8")
    return backup


def calibration_notes(cal_dir, keys, names):
    """After saving: which used cameras have no lens calibration yet, and whether the room calibration covers them
    all. Renaming or reordering cameras never matters: their calibration is filed under their key."""
    out = []
    if not cal_dir.is_dir():
        return out
    no_lens = [n for k, n in zip(keys, names) if not (cal_dir / f"intrinsics_{k}.json").is_file()]
    if no_lens:
        out.append(f"{', '.join(no_lens)} {'has' if len(no_lens) == 1 else 'have'} no lens calibration yet (step 2)")
    room_file = cal_dir / "room.json"
    if room_file.is_file():
        import json
        from calibration.room import cameras_in_order
        try:
            cameras_in_order(json.loads(room_file.read_text(encoding="utf-8")), keys)
        except (ValueError, KeyError, TypeError):
            out.append("the room calibration doesn't cover every camera now: redo it (step 2, 2_room_calibration.bat)")
    return out


# ---- the screen ------------------------------------------------------------------------------------------------

class Setup:
    def __init__(self, found, cfg, backend=None, old_ids=None):
        self.found = found
        self.cfg_cameras = dict(cfg["cameras"], **({"backend": backend} if backend else {}))
        self.backend = backend  # set when a different camera driver than the settings' one is needed
        self.exclude = [str(p) for p in (cfg["cameras"].get("exclude") or [])]
        c = cfg["cameras"]
        self.old = []  # [(id, name)] as saved now (ids as found now, when matched by USB device)
        old_keys = []
        try:
            self.old = list(zip(old_ids if old_ids is not None else c["ids"], camera_names(cfg)))
            old_turns = rotations(cfg)
            old_keys = camera_keys(cfg)
        except (ValueError, KeyError, TypeError):
            old_turns = []
        by_id = {f.id: f for f in found}
        self.name, self.turn = {}, {}
        self.calib_key = {}  # device id -> its calibration key: kept through renames and reorders
        self.order = []  # device ids in use, in slot order
        for slot, (i, n) in enumerate(self.old):
            if i in by_id and by_id[i].usable and i not in self.order:
                self.order.append(i)
                self.name[i] = n
                self.calib_key[i] = old_keys[slot] if slot < len(old_keys) else n
                self.turn[i] = old_turns[slot] if slot < len(old_turns) and old_turns[slot] in ROTATIONS else "none"
        taken = set(self.name.values())
        k = 1
        for f in found:
            if f.id not in self.name:
                while f"cam{k}" in taken:
                    k += 1
                self.name[f.id] = f"cam{k}"
                taken.add(f"cam{k}")
                self.turn[f.id] = "none"
        for f in found:  # a camera seen for the first time gets a key of its own, never one already used
            if f.id not in self.calib_key:
                self.calib_key[f.id] = new_key(set(self.calib_key.values()) | set(old_keys))
        for f in found:  # a focus locked before: set again (and again whenever it reconnects)
            want = camfocus.saved(c, self.calib_key[f.id])
            if want in ("stuck", "ring"):
                f.focus_verdict = want  # found before: not asked again (k is hidden for a focus-ring camera)
            elif want is not None and f.usable:
                f.focus_value = want
                if f.focus_settable:
                    f.set_focus(want)
        self.focusing = None  # the camera whose focus k is finding right now
        # cameras on a new USB port (found again by elimination: their settings are kept, saving records the port),
        # and cameras not found at all (several moved at once: a on a new picture makes it one of them)
        saved_paths = list(c.get("devices") or [])
        self.moved = [n for slot, (i, n) in enumerate(self.old) if i in self.order and slot < len(saved_paths)
                      and saved_paths[slot] and by_id[i].path and by_id[i].path != saved_paths[slot]]
        self.missing = [(slot, n, old_keys[slot] if slot < len(old_keys) else n,
                         old_turns[slot] if slot < len(old_turns) and old_turns[slot] in ROTATIONS else "none")
                        for slot, (i, n) in enumerate(self.old) if self.name.get(i) != n or i not in self.order]
        self.assigned = {}  # device id -> (its own name, key, turn) before a made it a missing camera
        self.pending = []   # what the background rescan found, for the main thread to show
        self.mode_testing = False
        self.suggested_mode = None  # (w, h, fourcc, fps, blockiness, fps got) after m, until y
        self.paths_dirty = bool(self.moved)
        self.sel = next((k for k, f in enumerate(found) if f.usable), 0)
        self.speed_queue = []  # with cameras.fps: auto, each camera is checked once, one per frame of the window
        self.speed_check = False
        self.typing = None  # the name being typed, or None
        self.message, self.message_color = "", WHITE
        self.saved = self.state()[:2] + (None, self.state()[3])  # a changed driver counts as unsaved
        self.confirm = None  # "quit", "save" or "exclude" when waiting for a second key press
        self.boxes = []  # (x0, y0, x1, y1, index into found) of the top tiles, in window pixels
        self.scale = 1.0
        self.offset = (0, 0)  # where the picture sits in the window (fullscreen centres it)
        self.single = None    # index into found: that camera alone, big, for aiming it
        self.guides = True    # faint centre cross and thirds in the big view
        self.full = True      # fit the picture to the window (always; the window itself can be moved and resized)
        self.fullscreen = False  # f: true fullscreen
        cal = cfg.get("calibration") or {}
        self.focus = FocusMeter(targets=focus_targets(cfg), background=True,
                                green_at=float(cal.get("focus_in_focus_at", 0.85)), hold_s=float(cal.get("focus_hold_s", 0.7)))  # the big view's focus meter, reset for each camera
        self.voice = None          # set by main(): says the focus milestones, and plays the focus sound
        self.focus_told = set()    # (camera, line): focus directions already spoken
        self.big_since = time.monotonic()
        self.focus_sound = load_prefs().get("focus_sound", True)  # v: soft ticks, faster as it gets sharper
        self.focus_on = False  # the focus assist runs only once started (C or its button), for the big view's camera
        self.picking = not self.order or bool(self.missing)  # the picker: at the start when none is chosen (or one is missing)
        self.focus_done = load_prefs().get("focus_done", {})  # calibration key -> {"how", "sharp"}: remembered
        self.screen = screen_size()

    def status(self, f):
        """("problem" | "checking" | "focus" | "dim" | "good", seconds of checking left). "dim" can be used, with a
        yellow note: more light helps it see the cat."""
        if not f.usable or f.problems():
            return "problem", 0
        left = f.checking_left()
        if left > 0:
            return "checking", left
        done, sharp = self.focus_done.get(self.calib_key[f.id]), f.sharp()
        saved = float(done.get("sharp") or 0) if done and done.get("measure") == 3 else 0  # (older: another scale)
        if not done or (sharp is not None and sharp < FOCUS_DROPPED * saved):
            return "focus", 0
        return ("dim" if f.notes() else "good"), 0

    def mark_focused(self, f, how):
        sharp = f.sharp()
        self.focus_done[self.calib_key[f.id]] = {"how": how, "sharp": round(sharp, 2) if sharp else None, "measure": 3,
                                                 "when": time.strftime("%Y-%m-%d %H:%M")}
        save_prefs(focus_done=self.focus_done)

    def overall(self):
        """One line: how many cameras passed the picture checks, and what the others are waiting for."""
        by_id = {f.id: f for f in self.found}
        st = {self.name[i]: self.status(by_id[i])[0] for i in self.order if i in by_id}
        good = [n for n, s in st.items() if s in ("good", "dim")]
        dim = [n for n, s in st.items() if s == "dim"]
        if not st:
            return "", WHITE
        if len(good) == len(st) and dim:
            return (f"All {len(st)} cameras passed the picture checks: press S to save, then go on to 2_calibrate_cameras. "
                    f"{', '.join(dim)}: a bit dark and grainy; more light helps it see the cat.", YELLOW)
        if len(good) == len(st):
            return (f"All {len(st)} cameras passed the picture checks: press S to save, then go on to "
                    "2_calibrate_cameras.", GREEN)
        why = {"problem": "fix it (click it)", "checking": "still checking", "focus": "focus it (click it)"}
        rest = ", ".join(f"{n} ({why[s]})" for n, s in st.items() if s not in ("good", "dim"))
        return (f"{len(good)} of {len(st)} cameras passed the picture checks. Not done yet: {rest}.",
                RED if "problem" in st.values() else YELLOW)

    def state(self):
        return (tuple(self.order), tuple((i, self.name[i], self.turn[i]) for i in self.order), self.backend,
                tuple(self.exclude))

    @property
    def dirty(self):
        return self.state() != self.saved or self.paths_dirty

    def say(self, text, color=WHITE):
        self.message, self.message_color = text, color

    # top: every camera found
    def top(self, tile_h):
        tiles = []
        for k, f in enumerate(self.found):
            frame = f.latest()
            img = np.zeros((tile_h, int(tile_h * 16 / 9), 3), np.uint8) if frame is None else frame.copy()
            if f.usable and self.turn[f.id] != "none":
                img = cv2.rotate(img, ROTATIONS[self.turn[f.id]])
            s = tile_h / img.shape[0]
            img = cv2.resize(img, (max(1, int(img.shape[1] * s)), tile_h), interpolation=cv2.INTER_AREA)
            if not f.usable:
                img = (cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) * 0.45).astype(np.uint8)
            used = f.id in self.order
            name = (self.typing + "_") if (self.typing is not None and k == self.sel) else self.name[f.id]
            lines = [(f"{k + 1}   {name}", WHITE)]
            if getattr(f, "opening", False):
                lines += [("OPENING ...", YELLOW)]
            elif f.excluded:
                lines += [("EXCLUDED: never opened", RED),
                          ("headset camera" if looks_like_headset(f.name) else "x to include it again", GREY)]
            elif f.usable:
                lines.append((f"USED, number {self.order.index(f.id) + 1}" if used else "not used (click to use it)",
                              GREEN if used else GREY))
                lines.append((TURN_LABEL[self.turn[f.id]], WHITE))
            else:
                lines += [("can't be used:", RED), (f.reason, RED)]
            lines.append(((f.name[:26] + " | " if f.name != "camera" else "") + f"id {f.id}", GREY))
            panel = img[: 14 + 30 * len(lines)]
            panel[:] = (panel * 0.35).astype(np.uint8)
            for j, (t, col) in enumerate(lines):
                outlined_text(img, t, (10, 30 + 30 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2, cv2.LINE_AA)
            if used and f.usable and LAPTOP_CAMERA.search(f.name or ""):  # a gentle note, never a block
                outlined_text(img, "Looks like a laptop or face camera: is it pointed at the room?",
                              (10, img.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, YELLOW, 1, cv2.LINE_AA)
            border = YELLOW if k == self.sel else GREEN if used else GREY
            cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), border, 6 if k == self.sel else 3)
            if getattr(self, "covered", None) == f.id and self.picking:
                cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), (255, 255, 0), 10)
                t = "This is the one you're covering"
                (tw, th), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                xx, yy = (img.shape[1] - tw) // 2, (img.shape[0] + th) // 2
                cv2.rectangle(img, (xx - 10, yy - th - 10), (xx + tw + 10, yy + 10), (30, 30, 30), -1)
                outlined_text(img, t, (xx, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2, cv2.LINE_AA)
            tiles.append(img)
        rows, row, width, boxes = [], [], 0, []
        max_w = max(1600, max(t.shape[1] for t in tiles))
        for k, t in enumerate(tiles):  # wrap into rows that fit about 1600 pixels
            if row and width + t.shape[1] > max_w:
                rows.append(row)
                row, width = [], 0
            row.append((k, t))
            width += t.shape[1]
        rows.append(row)
        full_w = max(sum(t.shape[1] for _, t in r) for r in rows)
        out = []
        for r_i, r in enumerate(rows):
            x = 0
            for k, t in r:
                boxes.append((x, r_i * tile_h, x + t.shape[1], (r_i + 1) * tile_h, k))
                x += t.shape[1]
            line = np.hstack([t for _, t in r])
            out.append(np.pad(line, ((0, 0), (0, full_w - line.shape[1]), (0, 0))))
        return np.vstack(out), boxes

    # bottom: only the used cameras, exactly as the preview and tracker windows lay them out
    def bottom(self, tile_h, checks=True):
        """The used cameras as the tracker shows them: just the name, top left. A camera with a problem gets a red
        frame and "Click to resolve issues" in the middle; the details are in its big view. Also sets
        self.bottom_tiles: (x0, y0, x1, y1, index into found) of each tile in this image."""
        by_id = {f.id: f for f in self.found}
        index = {f.id: k for k, f in enumerate(self.found)}
        tiles, ks = [], []
        for i in self.order:
            frame = by_id[i].latest()
            if frame is None:
                continue
            if self.turn[i] != "none":
                frame = cv2.rotate(frame, ROTATIONS[self.turn[i]])
            img = label_tile(frame, self.name[i], tile_h)
            by_id[i].sample()
            state, left = self.status(by_id[i])
            if checks and state != "problem":
                h, w = img.shape[:2]
                col = GREEN if state == "good" else YELLOW
                word = {"good": "CHECKS OK", "dim": "CHECKS OK, A BIT DARK", "focus": "FOCUS?  click it",
                        "checking": f"CHECKING  {int(left) // 60}:{int(left) % 60:02d}"}[state]
                cv2.rectangle(img, (0, 0), (w - 1, h - 1), col, 3)
                (tw, th), _ = cv2.getTextSize(word, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                x0 = w - tw - 22
                cv2.rectangle(img, (x0, 6), (w - 6, 14 + th + 10), (30, 30, 30), -1)
                outlined_text(img, word, (x0 + 8, 12 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
                if state == "checking":  # how far along
                    cv2.rectangle(img, (x0, 14 + th + 10), (w - 6, 14 + th + 15), (70, 70, 70), -1)
                    cv2.rectangle(img, (x0, 14 + th + 10), (x0 + int((w - 6 - x0) * (1 - left / WARMUP_S)), 14 + th + 15),
                                  YELLOW, -1)
            if checks and state == "problem":
                h, w = img.shape[:2]
                cv2.rectangle(img, (0, 0), (w - 1, h - 1), RED, 6)
                text = "Click to resolve issues" if by_id[i].connected else "NOT CONNECTED: plug it back in"
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                x, y = (w - tw) // 2, (h + th) // 2
                cv2.rectangle(img, (x - 12, y - th - 12), (x + tw + 12, y + 12), (30, 30, 30), -1)
                cv2.rectangle(img, (x - 12, y - th - 12), (x + tw + 12, y + 12), RED, 2)
                outlined_text(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2, cv2.LINE_AA)
            tiles.append(img)
            ks.append(index[i])
        rows = [list(range(2)), list(range(2, 4))] if len(tiles) == 4 else [list(range(len(tiles)))]
        self.bottom_tiles = []
        for r, row in enumerate(rows):  # the same layout as tile_grid
            x = 0
            for j in row:
                self.bottom_tiles.append((x, r * tile_h, x + tiles[j].shape[1], (r + 1) * tile_h, ks[j]))
                x += tiles[j].shape[1]
        return tile_grid(tiles)

    def frame(self):
        """The main window: the chosen cameras as the tracker will show them, each with its state, the overall line
        and the + ADD / REMOVE CAMERAS button; or the picker (every camera on the PC) while it's open."""
        W = 1600
        if self.picking:
            return self.picker_frame(W)
        title = ("WHAT THE TRACKER WILL SHOW   click a camera to see it big, with its checks" if self.order else
                 "WHAT THE TRACKER WILL SHOW")
        parts = [banner(W, title, YELLOW)]
        bottom = self.bottom(300)
        self.big_boxes = []
        if bottom is None:  # nothing chosen yet: say what to do
            empty = np.full((360, W, 3), 22, np.uint8)
            for j, (t, sc, col) in enumerate((("No cameras in use yet.", 1.2, WHITE),
                                              ("Click + ADD / REMOVE CAMERAS below (or press C) to pick your room cameras.",
                                               0.75, YELLOW))):
                (tw, _), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, sc, 2)
                outlined_text(empty, t, ((W - tw) // 2, 150 + 70 * j), cv2.FONT_HERSHEY_SIMPLEX, sc, col, 2, cv2.LINE_AA)
            parts.append(empty)
        else:
            sc = min(1.0, W / bottom.shape[1])
            if sc < 1:
                bottom = cv2.resize(bottom, (W, int(bottom.shape[0] * sc)), interpolation=cv2.INTER_AREA)
            left = (W - bottom.shape[1]) // 2
            y0 = parts[0].shape[0]
            self.big_boxes = [(left + x0 * sc, y0 + y0_ * sc, left + x1 * sc, y0 + y1 * sc, k)
                              for x0, y0_, x1, y1, k in self.bottom_tiles]
            parts.append(np.pad(bottom, ((0, 0), (left, W - bottom.shape[1] - left), (0, 0))))
        unused = sum(1 for f in self.found if f.usable and f.id not in self.order)
        bar = np.full((70, W, 3), 30, np.uint8)
        btn = ((W - 520) // 2, 10, (W + 520) // 2, 60)
        cv2.rectangle(bar, btn[:2], btn[2:], YELLOW, -1)
        label = "+ ADD / REMOVE CAMERAS  (C)" + (f"   {unused} not used" if unused else "")
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(bar, label, ((W - tw) // 2, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)
        y_bar = sum(q.shape[0] for q in parts)
        self.picker_btn = (btn[0], y_bar + btn[1], btn[2], y_bar + btn[3])
        parts.append(bar)
        line, col = self.overall()
        if line:
            parts.append(banner(W, line, col))
        from tools.keycaps import key_bar
        parts.append(key_bar(W, grid_keys(self)))
        if self.message and self.typing is None:
            parts.append(banner(W, self.message, self.message_color))
        bar = self.name_bar(W) if self.typing is not None else None
        if bar is not None:
            parts.append(bar)
        img = np.vstack(parts)
        self.place_name_btns(img.shape[0], bar)
        self.boxes = []
        self.help_box = help_button(img)
        return img

    def picker_frame(self, W):
        """Every camera on this PC, live: click one to use it (it's added at the end) or to stop using it. The
        selected one (yellow) can be renamed, turned, moved in the order or left out. DONE goes back."""
        self.cover_scan()
        top, boxes = self.top(260)
        sc = min(1.0, W / top.shape[1])
        if sc < 1:
            top = cv2.resize(top, (W, int(top.shape[0] * sc)), interpolation=cv2.INTER_AREA)
        left = (W - top.shape[1]) // 2
        parts = [banner(W, "ALL CAMERAS ON THIS PC   click one to use it, or click it again to stop using it. They're "
                           "used in the order you click them.", YELLOW),
                 banner(W, "Use at least 2 cameras; 3 or more works best in a furnished room. Not sure which camera is "
                           "which? Cover one with your hand.", WHITE)]
        y_title = parts[0].shape[0] + parts[1].shape[0]
        y0 = y_title
        self.boxes = [(left + x0 * sc, y0 + y0_ * sc, left + x1 * sc, y0 + y1 * sc, k) for x0, y0_, x1, y1, k in boxes]
        parts.append(np.pad(top, ((0, 0), (left, W - top.shape[1] - left), (0, 0))))
        bar = np.full((70, W, 3), 30, np.uint8)
        btn = ((W - 300) // 2, 10, (W + 300) // 2, 60)
        cv2.rectangle(bar, btn[:2], btn[2:], GREEN, -1)
        (tw, _), _ = cv2.getTextSize("DONE  (Esc)", cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
        cv2.putText(bar, "DONE  (Esc)", ((W - tw) // 2, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (20, 20, 20), 2, cv2.LINE_AA)
        y_bar = sum(q.shape[0] for q in parts)
        self.done_btn = (btn[0], y_bar + btn[1], btn[2], y_bar + btn[3])
        parts.append(bar)
        from tools.keycaps import key_bar
        parts.append(key_bar(W, picker_keys(self)))
        if self.message and self.typing is None:
            parts.append(banner(W, self.message, self.message_color))
        bar = self.name_bar(W) if self.typing is not None else None
        if bar is not None:
            parts.append(bar)
        img = np.vstack(parts)
        self.place_name_btns(img.shape[0], bar)
        self.help_box = help_button(img)
        self.back_box = back_button(img, self.help_box)
        return img

    def big(self):
        """The selected camera alone, as big as the screen allows, for aiming it: its name and state above, its
        checks, the aim tip and the keys below, so nothing covers the picture. Faint guide lines (g hides them)."""
        f = self.found[self.single]
        w, _ = self.screen if self.full else (1600, 900)
        name = (self.typing + "_") if self.typing is not None else self.name[f.id]
        used = f.id in self.order
        head = banner(w, f"{self.single + 1}   {name}   " + (f"USED, number {self.order.index(f.id) + 1}" if used else
                      "not used (Space uses it)") + f"   {TURN_LABEL[self.turn[f.id]]}", YELLOW)

        frame = f.latest()
        f.sample()
        if frame is not None and self.focus_on:
            self.focus.update(frame)  # the raw picture, before scaling: what the lens actually gives
            for said in self.focus.events:
                import logging
                logging.getLogger("camera_setup").info("focus meter (%s): %s  [sharpness %.1f, range %s-%s]",
                                                       self.name[f.id], said, self.focus.value or 0,
                                                       f"{self.focus.lo:.1f}" if self.focus.lo else "-",
                                                       f"{self.focus.hi:.1f}" if self.focus.hi else "-")
                if said.startswith("target found") and self.focus.target == "Board B":
                    self.say_once(f, FOCUS_BOARD_FOUND)
                if said == FOCUS_FOUND:
                    self.mark_focused(f, "assist")
                if self.voice and said in (FOCUS_FIND, FOCUS_FOUND):
                    if said == FOCUS_FOUND:
                        self.voice.focus_chime()  # the voice follows when the chime has finished
                    self.voice.say(said, force=True)
            self.focus.events.clear()
            if self.focus.rect is None and time.monotonic() - self.big_since > 4.0:
                self.say_once(f, FOCUS_HINT)  # once per camera: how to check its focus
            t = self.focus.level()
            if t is not None and time.monotonic() - getattr(self, "_focus_logged", 0) >= 1.0:
                self._focus_logged = time.monotonic()  # how close it gets, once a second (for tuning the threshold)
                import logging
                logging.getLogger("camera_setup").info("focus level (%s): %.2f (in focus at %.2f)%s", self.name[f.id], t,
                                                       self.focus.green_at, " on " + self.focus.target
                                                       if self.focus.target else "")
            # the focus sound: only once the meter knows the range (plain aiming stays quiet), and no ticking while
            # it's in focus (the chime said so)
            if self.voice and self.focus_sound and t is not None and not self.focus.green():
                self.voice.focus_tick(min(t / self.focus.green_at, 1.0))
        info = [banner(w, f"PROBLEM: {what}. {fix}", RED) for what, fix in f.problems()]
        info += [banner(w, f"{what}. {fix}", YELLOW) for what, fix in f.notes()]
        info += [colour_bar(w, (f.checks() + ([f.tracker_line()] if self.speed_check else [])) if f.usable else [(f"can't be used: {f.reason}", RED)]),
                 banner(w, AIM_TIP, GREEN),
                __import__("tools.keycaps", fromlist=["key_bar"]).key_bar(w, big_keys(self))]
        if self.message and self.typing is None:
            info.append(banner(w, self.message, self.message_color))
        name_bar = self.name_bar(w) if self.typing is not None else None
        if name_bar is not None:
            info.append(name_bar)
        img = np.zeros((720, 1280, 3), np.uint8) if frame is None else frame
        if frame is not None and self.focus_on and self.focus.rect is not None:  # faintly: what it measures
            x, y, rw, rh = self.focus.rect
            g = img.copy()
            cv2.rectangle(g, (x, y), (x + rw, y + rh), (80, 220, 80), 2, cv2.LINE_AA)
            img = cv2.addWeighted(g, 0.6, img, 0.4, 0)
        if f.usable and self.turn[f.id] != "none":
            img = cv2.rotate(img, ROTATIONS[self.turn[f.id]])
        h_room = (self.screen[1] if self.full else 900) - head.shape[0] - sum(b.shape[0] for b in info)
        panel_w = max(260, w // 6)  # the focus circle's panel, beside the picture: it never covers it
        sc = min((w - panel_w) / img.shape[1], max(h_room, 200) / img.shape[0])
        img = cv2.resize(img, (int(img.shape[1] * sc), int(img.shape[0] * sc)),
                         interpolation=cv2.INTER_LINEAR if sc > 1 else cv2.INTER_AREA)
        if self.guides:  # thin and faint: they help to aim without hiding anything
            g = img.copy()
            hh, ww = img.shape[:2]
            for x in (ww // 3, 2 * ww // 3):
                cv2.line(g, (x, 0), (x, hh - 1), (200, 200, 200), 1, cv2.LINE_AA)
            cv2.line(g, (0, 2 * hh // 3), (ww - 1, 2 * hh // 3), (200, 200, 200), 1, cv2.LINE_AA)
            cv2.line(g, (0, hh // 3), (ww - 1, hh // 3), (255, 255, 255), 2, cv2.LINE_AA)  # heads above, floor below
            cv2.line(g, (ww // 2 - 25, hh // 2), (ww // 2 + 25, hh // 2), (255, 255, 255), 2, cv2.LINE_AA)
            cv2.line(g, (ww // 2, hh // 2 - 25), (ww // 2, hh // 2 + 25), (255, 255, 255), 2, cv2.LINE_AA)
            img = cv2.addWeighted(g, 0.45, img, 0.55, 0)
            for label, dy in (("heads above", -10), ("floor below", 24)):  # small, at the edge: hides nothing
                outlined_text(img, label, (10, hh // 3 + dy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1, cv2.LINE_AA)
        room_w = w - panel_w
        left = (room_w - img.shape[1]) // 2
        img = np.pad(img, ((0, 0), (left, room_w - img.shape[1] - left), (0, 0)))
        if self.focus_on:
            panel = self.focus.panel(panel_w, img.shape[0])
            box = (14, panel.shape[0] - 70, panel_w - 14, panel.shape[0] - 16)  # at the bottom of the panel
            cv2.rectangle(panel, box[:2], box[2:], RED, 3)
            t = "STOP FOCUS ASSIST (C)"
            (tw, th), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.putText(panel, t, (box[0] + (box[2] - box[0] - tw) // 2, box[1] + (box[3] - box[1] + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, RED, 2, cv2.LINE_AA)
            self.panel_btns = [(room_w + box[0], head.shape[0] + box[1], room_w + box[2], head.shape[0] + box[3],
                                "stop")]
        else:
            panel, btns = self.focus_start_panel(f, panel_w, img.shape[0])
            self.panel_btns = [(room_w + x0, head.shape[0] + y0, room_w + x1, head.shape[0] + y1, a)
                               for x0, y0, x1, y1, a in btns]
        self.focus_panel_x = room_w
        img = np.hstack([img, panel])
        self.boxes = []
        out = np.vstack([head, img] + info)
        self.place_name_btns(out.shape[0], name_bar)
        self.help_box = help_button(out)
        self.back_box = back_button(out, self.help_box)  # how to get back (a click on the picture works too)
        return out

    def focus_start_panel(self, f, width, height):
        """Beside the big picture until the focus assist is started. Focus OK: says so, when it was checked, and a
        small "use the focus assist anyway" button. Not done yet: a big START FOCUS ASSIST button, and SKIP when the
        picture is already sharp enough. Returns (panel, [(x0, y0, x1, y1, action)])."""
        img = np.full((height, width, 3), 30, np.uint8)
        done = self.focus_done.get(self.calib_key[f.id])
        sharp = f.sharp()
        ok = self.status(f)[0] in ("good", "dim") or (done and self.status(f)[0] == "checking")
        btns = []

        def button(y, h, text, fill, text_col):  # plain dark (or coloured) text on the button: no outline
            box = (14, y, width - 14, y + h)
            if fill is not None:
                cv2.rectangle(img, box[:2], box[2:], fill, -1)
            else:
                cv2.rectangle(img, box[:2], box[2:], text_col, 2)
            sc = 0.6
            while cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, sc, 2)[0][0] > box[2] - box[0] - 20 and sc > 0.4:
                sc -= 0.05
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, sc, 2)
            cv2.putText(img, text, (box[0] + (box[2] - box[0] - tw) // 2, box[1] + (h + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, sc, text_col, 2, cv2.LINE_AA)
            return box

        y = 40
        if ok:
            cv2.putText(img, "FOCUS: OK", (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.85, GREEN, 2, cv2.LINE_AA)
            how = "focus assist" if done and done.get("how") == "assist" else "sharp enough, skipped"
            text = (f"Checked {done.get('when', '')} ({how})." if done else "") + (
                f" Sharpness now {sharp:.1f}." if sharp is not None else "")
            y += 20
            for line in _wrap(text.strip(), width - 28, 0.55):
                y += 24
                cv2.putText(img, line, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
            y += 24
            btns.append(button(y, 44, "Use the focus assist anyway (C)", None, WHITE) + ("start",))
            return img, btns
        cv2.putText(img, "FOCUS: NOT DONE YET", (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, YELLOW, 2, cv2.LINE_AA)
        y += 20
        btns.append(button(y, 60, "START FOCUS ASSIST (C)", YELLOW, (20, 20, 20)) + ("start",))
        y += 76
        can_skip = sharp is not None and sharp >= FOCUS_SKIP_SHARPNESS
        if can_skip:
            btns.append(button(y, 52, "SKIP: IT'S SHARP ENOUGH (O)", None, GREEN) + ("skip",))
            y += 68
        if sharp is None and getattr(f, "noise_part", 0) > NOISE_PART_MAX:
            text = ("The room is too dim to judge sharpness from the picture alone (the camera's noise looks like "
                    "detail). Use the focus assist, or add light.")
        elif sharp is None:
            text = "Measuring how sharp the picture is..."
        elif can_skip:
            text = f"Sharpness {sharp:.1f}: already sharp. Skip it, or use the focus assist to be sure."
        else:
            text = (f"Sharpness {sharp:.1f}: a bit soft. The focus assist guides you with a circle and a sound while "
                    "you turn the focus ring.")
        for line in _wrap(text, width - 28, 0.55):
            y += 24
            cv2.putText(img, line, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
        return img, btns

    def present(self):
        """What the window shows: the grid or the big view, fitted to the screen (centred, fullscreen) or kept
        under 1800 x 1000 in a window. Clicks are mapped back through the same scale and offset."""
        for g in self.found:  # watched all the time, in either view
            g.sample()
            if g.usable and g.id in self.order:  # its readings to the log once, when its checking has finished
                st = self.status(g)[0]
                if st != "checking" and not getattr(g, "_logged", False):
                    g._logged = True
                    self.log_readings(g, "checked")
                elif st == "checking":
                    g._logged = False
        img = self.big() if self.single is not None else self.frame()
        if self.full:
            sw, sh = self.screen
            s = min(sw / img.shape[1], sh / img.shape[0])
        else:
            sw = sh = None
            s = min(1.0, 1800 / img.shape[1], 1000 / img.shape[0])
        if abs(s - 1) > 1e-3:
            img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                             interpolation=cv2.INTER_LINEAR if s > 1 else cv2.INTER_AREA)
        ox = oy = 0
        if self.full:
            ox, oy = (sw - img.shape[1]) // 2, (sh - img.shape[0]) // 2
            img = np.pad(img, ((oy, sh - img.shape[0] - oy), (ox, sw - img.shape[1] - ox), (0, 0)))
        self.scale, self.offset = s, (ox, oy)
        return img

    def save_focus(self, f, value):
        """cameras.focus: {<camera key>: value} in the settings file, after a backup."""
        key = self.calib_key[f.id]
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        table = dict(camfocus.saved_table(text))
        table[key] = value if isinstance(value, str) else int(round(value)) if float(value).is_integer() else float(value)
        flow = "{" + ", ".join(f"{k}: {v}" for k, v in table.items()) + "}"
        backup = DATA / "backups" / f"cameras_{time.strftime('%Y%m%d-%H%M%S')}.yaml"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_CONFIG, backup)
        DEFAULT_CONFIG.write_text(_set_or_add_key(text, "focus", flow, FOCUS_COMMENT), encoding="utf-8")

    def find_focus(self, f, settle_s=0.45, frames=3):
        """k: autofocus off, then the focus stepped across its range (coarse, then fine around the best), measuring
        Board B's area (or the whole picture), and the best one set and saved. In the background: the picture and
        the meter keep going meanwhile."""
        if self.focusing is not None:
            return
        self.focusing = f.id
        fi = f.focus_info
        if fi["autofocus"] == 1 and not fi["can_turn_off"]:  # the driver refuses to switch it off
            f.focus_verdict = "stuck"
            self.save_focus(f, "stuck")
            logging_info("focus lock (%s, experimental): autofocus can't be switched off (%s)", self.name[f.id], fi)
            self.say(camfocus.STUCK + ". A camera with a fixed focus or a focus ring works better.", RED)
            self.focusing = None
            return
        lo, hi = fi["range"] or (0.0, 255.0)
        self.say("Experimental: finding the focus. Keep Board B still, and stay out of the picture...", YELLOW)
        logging_info("focus lock (%s, experimental): started; the driver reports %s", self.name[f.id], f.focus_info)
        if self.voice:
            self.voice.say("This is experimental, and hasn't been tested on real autofocus cameras yet. "
                           "Keep Board B still.", force=True)

        def measure():
            vals = []
            last = None
            t_end = time.monotonic() + 1.5
            while len(vals) < frames and time.monotonic() < t_end:
                fr = f.latest()
                if fr is not None and fr is not last:
                    last = fr
                    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY) if fr.ndim == 3 else fr
                    r = self.focus.rect
                    if r is not None:
                        x, y, w, h = r
                        vals.append(float(np.median(tile_sharpness(g[y:y + h, x:x + w], (1, 1)))))
                    else:
                        vals.append(float(np.median(tile_sharpness(g))))
                time.sleep(0.01)
            return float(np.median(vals)) if vals else 0.0

        def try_values(values):
            scores = []
            for v in values:
                f.set_focus(v)
                time.sleep(settle_s)  # the lens moves, and new frames arrive
                scores.append((measure(), v))
            return scores

        def run():
            try:
                step = f.focus_info.get("step", 1)
                coarse = try_values(camfocus.sweep_values(lo, hi, 12, step))
                best = max(coarse)[1]
                gap = (hi - lo) / 11
                fine = try_values(camfocus.sweep_values(max(lo, best - gap), min(hi, best + gap), 9, step))
                score, best = max(coarse + fine)
                least = min(coarse)[0]
                logging_info("focus lock (%s): coarse %s; fine %s", self.name[f.id],
                             [(v, round(sc, 1)) for sc, v in coarse], [(v, round(sc, 1)) for sc, v in fine])
                if score < 1.25 * max(least, 1e-6):  # the picture didn't change: the lens isn't moved by the computer
                    f.focus_verdict = "ring"
                    self.save_focus(f, "ring")  # remembered: k isn't offered for it again
                    with f._lock:
                        f.focus_jobs = []
                    if f.cap is not None and f.focus_info["autofocus"] == 1:
                        camfocus.restore_autofocus(f.cap)
                    logging_info("focus lock (%s): no effect on the picture (sharpness %.1f to %.1f): its focus is "
                                 "its ring; nothing saved", self.name[f.id], least, score)
                    self.say("Changing the focus from the computer made no difference: this camera's focus is its "
                             "ring. Turn it by hand (see the focus steps). Nothing was saved.", YELLOW)
                    if self.voice:
                        self.voice.say("No difference. This camera's focus is set by its ring.", force=True)
                    return
                f.set_focus(best)
                time.sleep(settle_s)
                f.focus_value, f.focus_verdict = best, "locked"
                self.save_focus(f, best)
                logging_info("focus lock (%s): %g, sharpness %.1f (%s)", self.name[f.id], best, score,
                             "Board B" if self.focus.rect is not None else "whole picture")
                self.focus.reset(keep_target=True)
                self.say(f"Focus locked at {best:g} and saved.", GREEN)
                if self.voice:
                    self.voice.focus_chime()
                    self.voice.say("Focus locked.", force=True)
            except Exception as e:  # noqa: BLE001
                self.say(f"Finding the focus didn't work: {e}", RED)
            finally:
                self.focusing = None
        threading.Thread(target=run, name="find focus", daemon=True).start()

    def say_once(self, f, text):
        """A focus direction, spoken at most once per camera while this screen is open (they're not repeated)."""
        if self.voice and (f.id, text) not in self.focus_told:
            self.focus_told.add((f.id, text))
            self.voice.say(text, force=True)

    def leave_big(self):
        """Back to the main window (or the picker); a running focus assist stops with it."""
        self.single = None
        self.focus_on = False
        self.say("")

    def focus_action(self, a):
        f = self.found[self.single]
        if a == "stop":
            self.focus_on = False
            self.say("Focus assist off.")
            return
        if a == "start":
            self.focus_on = True
            self.focus.reset()
            self.big_since = time.monotonic()
            self.say("Focus assist on: turn the focus ring slowly. Esc goes back.", YELLOW)
        elif a == "skip":
            sharp = f.sharp()
            if sharp is not None and sharp >= FOCUS_SKIP_SHARPNESS:
                self.mark_focused(f, "skipped, sharp enough")
                self.say(f"{self.name[f.id]}: focus skipped, its picture is sharp enough ({sharp:.1f}).", GREEN)
            else:
                self.say("Not sharp enough to skip: use the focus assist (C).", YELLOW)

    def open_big(self, k):
        f = self.found[k]
        if f.excluded:
            self.say(f"{f.name} is excluded, so it's never opened. Press x to include it again", YELLOW)
            return
        if self.single != k:
            self.focus.reset()  # sharpness is only compared within one camera's view
            self.focus_on = False  # started by its button for each camera, never by itself
            self.big_since = time.monotonic()
        self.sel, self.single, self.confirm = k, k, None
        self.say("")

    def click(self, x, y):
        x, y = (x - self.offset[0]) / self.scale, (y - self.offset[1]) / self.scale
        if self.typing is not None:  # naming: a click on one of the names
            for x0, y0, x1, y1, n in getattr(self, "name_btns", []):
                if x0 <= x < x1 and y0 <= y < y1:
                    self.give_name(n)
            return
        hb = getattr(self, "help_box", None)
        if hb and hb[0] <= x < hb[2] and hb[1] <= y < hb[3]:
            self.help_open = not getattr(self, "help_open", False)
            return
        if self.single is not None:
            bb = getattr(self, "back_box", None)
            if bb and bb[0] <= x < bb[2] and bb[1] <= y < bb[3]:
                self.leave_big()
                return
            for x0, y0, x1, y1, a in getattr(self, "panel_btns", []):  # the focus panel's buttons
                if x0 <= x < x1 and y0 <= y < y1:
                    self.focus_action(a)
                    return
            if getattr(self, "focus_panel_x", None) is not None and x >= self.focus_panel_x:
                return  # elsewhere on the focus panel: nothing
            self.leave_big()  # a click anywhere else on the picture goes back too
            return
        if self.picking:
            db = getattr(self, "done_btn", None)
            bb = getattr(self, "back_box", None)
            if (db and db[0] <= x < db[2] and db[1] <= y < db[3]) or (bb and bb[0] <= x < bb[2] and bb[1] <= y < bb[3]):
                self.picking = False
                self.say("")
                return
            for x0, y0, x1, y1, k in self.boxes:  # a camera: use it, or stop using it
                if x0 <= x < x1 and y0 <= y < y1:
                    self.sel = k
                    self.toggle_use(self.found[k])
            return
        pb = getattr(self, "picker_btn", None)
        if pb and pb[0] <= x < pb[2] and pb[1] <= y < pb[3]:
            self.picking = True
            return
        for x0, y0, x1, y1, k in getattr(self, "big_boxes", []):  # a camera the tracker shows: see it big
            if x0 <= x < x1 and y0 <= y < y1:
                self.sel = k
                self.open_big(k)
                return

    NAMES = ("North", "East", "South", "West")

    def name_bar(self, W):
        """While naming: one-click names (the walls; a name another camera has is greyed), then the typed one."""
        f = self.found[self.sel] if self.single is None else self.found[self.single]
        taken = {self.name[g.id] for g in self.found if g.id != f.id}
        bar = np.full((112, W, 3), 30, np.uint8)
        outlined_text(bar, f"Name {self.name[f.id]}: click one, or type a name (Enter keeps it, Esc cancels):  "
                           f"{self.typing}_", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, YELLOW, 2, cv2.LINE_AA)
        self._name_btns_rel, x = [], 12
        for n in self.NAMES:
            free = n not in taken
            box = (x, 48, x + 150, 100)
            cv2.rectangle(bar, box[:2], box[2:], YELLOW if free else (70, 70, 70), -1 if free else 2)
            (tw, _), _ = cv2.getTextSize(n, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.putText(bar, n, (x + (150 - tw) // 2, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (20, 20, 20) if free else (110, 110, 110), 2, cv2.LINE_AA)
            if free:
                self._name_btns_rel.append(box + (n,))
            x += 166
        return bar

    def place_name_btns(self, height, bar):
        """The name buttons in window coordinates (the name bar is the last strip of the picture)."""
        if bar is None:
            self.name_btns = []
            return
        y = height - bar.shape[0]
        self.name_btns = [(x0, y + y0, x1, y + y1, n) for x0, y0, x1, y1, n in self._name_btns_rel]

    def give_name(self, name):
        """Name the camera being named (a click on a name button), as Enter does with a typed one."""
        self.typing = name
        self.key(13)

    def cover_scan(self, now=None):
        """The picker's "cover to find": the one camera whose picture suddenly went much darker or blank (a hand
        over it) for half a second, against its own recent picture. Several at once (the room light off) counts as
        none. Sets self.covered (a camera's handle, or None)."""
        now = time.monotonic() if now is None else now
        low = []
        for f in self.found:
            frame = f.latest() if f.usable else None
            if frame is None:
                continue
            g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame, (64, 36),
                           interpolation=cv2.INTER_AREA).astype(np.float32)
            b, d = float(g.mean()), float(cv2.Laplacian(g, cv2.CV_32F).var())
            st = f.__dict__.setdefault("_cover", {"b": b, "d": d, "since": None})
            dark = b < 0.45 * st["b"] or d < 0.2 * st["d"]
            if dark:
                st["since"] = st["since"] or now
                if now - st["since"] >= COVER_HOLD_S:
                    low.append(f.id)
            else:
                st["since"] = None
                st["b"] += 0.1 * (b - st["b"])  # its normal picture, learned slowly (only while not covered)
                st["d"] += 0.1 * (d - st["d"])
        self.covered = low[0] if len(low) == 1 else None

    def toggle_use(self, f):
        """Use this camera (added at the end of the order) or stop using it."""
        if getattr(f, "opening", False):
            self.say(f"{self.name[f.id]} is still opening: one moment.", YELLOW)
        elif not f.usable:
            self.say(f"{self.name[f.id]} is left out (excluded): press x to include it first" if f.excluded
                     else f"This camera can't be used: {f.reason}", RED)
        elif f.id in self.order:
            self.order.remove(f.id)
            self.say(f"{self.name[f.id]} is not used now")
        else:
            self.order.append(f.id)
            self.say(f"{self.name[f.id]} is used, as number {len(self.order)}. N names it (the wall it's on is a good name).",
                     GREEN)

    def select(self, k):
        if 0 <= k < len(self.found) and self.typing is None:
            self.sel = k
            self.confirm = None
            f = self.found[k]
            if f.excluded:
                self.say(f"{f.name} is excluded, so it's never opened. Press x to include it again", YELLOW)
            else:
                self.say(f"Selected {self.name[f.id]}" if f.usable else f"This camera can't be used: {f.reason}",
                         WHITE if f.usable else RED)

    def exclude_key(self, f):
        # opening a camera takes 2-3 s (closing a quarter of a second): it happens in the background, and X on a
        # camera that's still opening is ignored, so pressing X over and over can't queue up a freeze
        if getattr(f, "opening", False):
            self.say(f"{self.name[f.id]} is still opening: one moment.", YELLOW)
            return
        if time.monotonic() - getattr(f, "_x_done", -9) < X_COOLDOWN_S:  # held down: not straight back in
            return
        if f.excluded:  # include it again: drop every rule that matches it, then open it (in the background)
            f._x_done = time.monotonic()
            matching = [p for p in self.exclude if p.strip() and p.lower() in f"{f.name} {f.path or ''}".lower()]
            self.exclude = [p for p in self.exclude if p not in matching]
            f.opening = True
            index = device_index_now(f)

            def open_it():
                try:
                    g = Found(index, self.cfg_cameras, f.name, f.path)
                except Exception as e:  # noqa: BLE001  (said on screen, never silent)
                    g = None
                    f.open_error = str(e)
                self.pending.append(("included", g, (f, matching)))

            threading.Thread(target=open_it, name="camera open", daemon=True).start()
            self.say(f"Opening {self.name[f.id]} ...", YELLOW)
            return
        if self.confirm != "exclude":
            self.confirm = "exclude"
            self.say(f"Press x again to exclude {self.name[f.id]} ({f.name}): it will never be opened again,"
                     " by this screen or the tracker", YELLOW)
            return
        self.confirm = None
        f._x_done = time.monotonic()
        f.close()
        f.excluded = True
        if f.id in self.order:
            f.was_used_at = self.order.index(f.id)  # including it again puts it back there
            self.order.remove(f.id)
        self.exclude.append(f.path or f.name)
        self.single = None  # excluded from its big view: back to every camera, where it shows as excluded
        self.say(f"{self.name[f.id]} is excluded: never opened. X on it includes it again; s saves.", GREEN)

    def key(self, code):
        """Handle one key. Returns False to close the window."""
        f = self.found[self.sel]
        ch = code & 0xFF if code < 0x10000 else None
        if self.typing is not None:
            if ch == 13:
                name = self.typing.strip()
                others = {self.name[g.id] for g in self.found if g.id != f.id}
                if not NAME_OK.match(name):
                    self.say("A name needs 1 to 20 letters, numbers, - or _ (no spaces)", RED)
                elif name in others:
                    self.say(f"Another camera is already called {name}", RED)
                else:
                    self.name[f.id] = name
                    self.say(f"Renamed to {name}", GREEN)
                self.typing = None
            elif ch == 27:
                self.typing = None
                self.say("Rename cancelled")
            elif ch == 8:
                self.typing = self.typing[:-1]
            elif ch is not None and 32 <= ch < 127 and len(self.typing) < 20:
                self.typing += chr(ch)
            return True
        if ch in (ord("?"), ord("/")):
            self.help_open = not getattr(self, "help_open", False)
            return True
        if self.single is None and self.picking and ch in (27, 13):
            self.picking = False
            self.confirm = None
            self.say("")
            return True
        if self.single is None and not self.picking and ch == ord("c"):
            self.picking = True
            return True
        if self.single is not None:  # the big view: switch camera, go back, or do what makes sense for one camera
            if ch in (13, 27, ord("q")):
                self.leave_big()
                return True
            if ch is not None and ord("1") <= ch <= ord("9"):
                k = ch - ord("1")
                if k == self.single:
                    self.single = None
                elif k < len(self.found):
                    self.open_big(k)
                return True
            if ch == 9 or code in (KEY_LEFT, KEY_RIGHT) or ch in (ord("["), ord("]")):
                step = -1 if code == KEY_LEFT or ch == ord("[") else 1
                order = [k for k in range(len(self.found)) if not self.found[k].excluded]
                if order:
                    i = order.index(self.single) if self.single in order else 0
                    self.open_big(order[(i + step) % len(order)])
                return True
            if ch == ord("c"):
                if self.focus_on:
                    self.focus_on = False
                    self.say("Focus assist off.")
                else:
                    self.focus_action("start")
                return True
            if ch == ord("o"):
                self.focus_action("skip")
                return True
            if ch == ord("g"):
                self.guides = not self.guides
                return True
            f = self.found[self.single]
            fi = getattr(f, "focus_info", None)
            if ch == ord("k") and f.usable and getattr(f, "focus_verdict", None) != "ring" and (getattr(f, "focus_settable", False)
                                                or (fi and fi["autofocus"] == 1 and not fi["can_turn_off"])):
                self.find_focus(f)
                return True
            if ch in (ord("-"), ord("_"), ord("="), ord("+")) and getattr(f, "focus_settable", False) and f.usable and not self.focusing:
                lo, hi = (f.focus_info["range"] or (0.0, 255.0))
                fstep = f.focus_info.get("step", 1)
                step = max(fstep, camfocus.snap((hi - lo) / 50, fstep))
                now = f.focus_value if f.focus_value is not None else (f.focus_info["focus"] or lo)
                value = min(max(now + (step if ch in (ord("="), ord("+")) else -step), lo), hi)
                f.focus_value = value
                f.set_focus(value)
                self.save_focus(f, value)
                logging_info("focus lock (%s, experimental): nudged to %g", self.name[f.id], value)
                self.say(f"Focus {value:g} (saved). The meter shows if it's better.", GREEN)
                return True
            if ch == ord("b"):
                self.focus.reset(keep_target=True)  # the card is still where it was
                self.say("Focus meter started over: turn the ring slowly from one end to the other")
                return True
            if ch == ord("v"):
                self.focus_sound = not self.focus_sound
                save_prefs(focus_sound=self.focus_sound)  # remembered for next time
                self.say("Focus sound on: the ticks get faster as it gets sharper" if self.focus_sound
                         else "Focus sound off (v turns it back on)")
                if self.voice and self.focus_sound:
                    self.voice.say("Focus sound on", force=True)
                return True
            if ch == ord("f"):
                self.fullscreen = not self.fullscreen
                return True
            if ch not in (ord("r"), ord("n"), ord(" "), ord("p"), ord("s"), ord("m"), ord("y"), ord("x")):
                return True  # the rest (reorder) only from the grid
        if ch == ord("f"):
            self.fullscreen = not self.fullscreen
            return True
        if ch == 13:
            self.open_big(self.sel)
            return True
        if ch in (ord("q"), 27):
            if self.dirty and self.confirm != "quit":
                self.confirm = "quit"
                self.say("You have unsaved changes: press q again to quit without saving, or s to save", YELLOW)
                return True
            return False
        if ch == ord("s"):
            return self.save_key()
        if ch == ord("x"):
            self.exclude_key(f)
            return True
        if ch == ord("p"):
            if f.usable and self.cfg_cameras.get("backend") == "dshow":
                f.want_settings = True
                self.say(f"Opening {self.name[f.id]}'s driver settings (it may open behind this window)")
            else:
                self.say("Driver settings open only for a usable camera, with the dshow camera driver", YELLOW)
            return True
        self.confirm = None
        if ch is not None and ord("1") <= ch <= ord("9"):
            if ch - ord("1") == self.sel:  # its number again: show it big
                self.open_big(self.sel)
            else:
                self.select(ch - ord("1"))
        elif ch == ord(" "):
            self.toggle_use(f)
        elif ch == ord("a"):
            self.assign_key(f)
        elif ch == ord("m"):
            self.mode_test_key(f)
        elif ch == ord("y") and self.suggested_mode is not None:
            self.apply_mode()
        elif ch == ord("n"):
            self.typing = ""
        elif ch == ord("r") and f.usable:
            self.turn[f.id] = TURNS[(TURNS.index(self.turn[f.id]) + 1) % 4]
            self.say(f"{self.name[f.id]}: {TURN_LABEL[self.turn[f.id]]}")
        elif ch in (ord("["), ord("]"), ord("<"), ord(">"), ord(","), ord(".")) or code in (KEY_LEFT, KEY_RIGHT):
            if f.id not in self.order:
                self.say("Use this camera first (space), then move it", YELLOW)
            else:
                i = self.order.index(f.id)
                j = i - 1 if (ch in (ord("["), ord("<"), ord(",")) or code == KEY_LEFT) else i + 1
                if 0 <= j < len(self.order):
                    self.order[i], self.order[j] = self.order[j], self.order[i]
                    self.say(f"{self.name[f.id]} is now number {j + 1}")
        return True

    def rescan(self, devices=None):
        """Look at Windows' device list (call it off the frame loop, every RESCAN_EVERY_S): reopen unplugged cameras
        that are back (same port; or a new port when one camera is unplugged and one device is new), and open any
        other new camera as a tile. Changes are queued for apply_rescan on the main thread."""
        devs = list_devices() if devices is None else devices
        if not plausible_devices(devs):  # a bad read (mid-unplug, or the wrong category): try again next time
            return
        known = {f.path for f in self.found if f.path}
        gone = [f for f in self.found if getattr(f, "state", "ok") == "unplugged"]
        new = [(k, n, pth) for k, (n, pth) in enumerate(devs) if pth not in known
               and not excluded(self.cfg_cameras, n, pth)]
        paths = [pth for _, pth in devs]
        for f in gone:
            if f.path in paths and f.reopen(paths.index(f.path), f.path):
                self.pending.append(("back", f, False))
        gone = [f for f in gone if f.state == "unplugged"]
        waiting = [m for m in self.missing if m not in [x[3] for x in self.assigned.values()]]
        if len(gone) == 1 and len(new) == 1 and not waiting:  # one unplugged, one new device: it moved port
            k, n, pth = new.pop()
            if gone[0].reopen(k, pth):
                self.pending.append(("back", gone[0], True))
        elif len(waiting) == 1 and len(new) == 1 and not gone:  # missing since the start, and now one new device
            k, n, pth = new.pop()
            f = Found(k, self.cfg_cameras, n, pth)
            self.pending.append(("assign", f, waiting[0]))
        for k, n, pth in new:  # a camera plugged in while the screen is open
            if pth in {f.path for f in self.found}:
                continue
            f = Found(k, self.cfg_cameras, n, pth)
            self.pending.append(("new", f, False))

    def finish_include(self, g, f, matching):
        """A camera included again has opened (in the background): it takes its place back."""
        f.opening = False
        if g is None:  # still excluded, as it was
            self.exclude += [m for m in matching if m not in self.exclude]
            self.say(f"{self.name[f.id]} couldn't be opened: {getattr(f, 'open_error', 'unknown error')}", RED)
            return
        g.id = f.id  # the screen's handle (names, order, calibration key) stays with this camera
        k = next((k for k, h in enumerate(self.found) if h is f), None)
        if k is None:  # gone from the list meanwhile
            g.close()
            return
        self.found[k] = g
        was = getattr(f, "was_used_at", None)
        if g.usable and was is not None and g.id not in self.order:  # back where it was in the tracker's view
            self.order.insert(min(was, len(self.order)), g.id)
        others = [h.name for h in self.found if h.excluded and any(p.lower() in f"{h.name} {h.path or ''}".lower()
                                                                   for p in matching)]
        self.say(f"{self.name[g.id]} is included again"
                 + (f", but it can't be opened: {g.reason}" if g.reason else
                    " and used again, as before" if g.id in self.order else ": press space to use it")
                 + (f". Rule removed: {', '.join(matching)}" if matching else "")
                 + (f". That rule also hid {', '.join(others)}: they show after saving and running this again"
                    if others else ""), GREEN if g.usable else YELLOW)

    def apply_rescan(self):
        """On the main thread: show what rescan found, and cameras opened in the background (included again)."""
        while self.pending:
            what, f, moved = self.pending.pop(0)
            if what == "included":
                self.finish_include(f, *moved)
                continue
            if what == "assign":  # a camera that wasn't there at the start: it takes its saved settings back
                m = moved
                f.id = max([g.id for g in self.found] + [-1]) + 1
                self.found.append(f)
                if not f.usable or m not in self.missing:
                    self.name[f.id], self.turn[f.id] = f"cam{len(self.found)}", "none"
                    self.calib_key[f.id] = new_key(set(self.calib_key.values()))
                    continue
                self.missing.remove(m)
                slot, name, key, turn = m
                self.name[f.id], self.calib_key[f.id], self.turn[f.id] = name, key, turn
                self.order.insert(min(slot, len(self.order)), f.id)
                self.paths_dirty = True
                self.say(f"{spoken(name, True)} is plugged in now: kept its settings. Press s to save its USB port.",
                         GREEN)
                continue
            if what == "new":
                f.id = max([g.id for g in self.found] + [-1]) + 1  # a handle of its own (its Windows number is apart)
                self.found.append(f)
                taken = set(self.name.values())
                k = 1
                while f"cam{k}" in taken:
                    k += 1
                self.name[f.id], self.turn[f.id] = f"cam{k}", "none"
                self.calib_key[f.id] = new_key(set(self.calib_key.values()))
                self.say(f"New camera found: {self.name[f.id]}. Select it and press space to use it.", GREEN)
            else:
                if moved:
                    self.paths_dirty = True
                self.say(f"{spoken(self.name[f.id], True)} is back" + (" on a new USB port: press s to save that."
                                                                      if moved else "."), GREEN)
        for f in self.found:  # newly unplugged: say it once
            if getattr(f, "state", "ok") == "unplugged" and not getattr(f, "_told_unplugged", False):
                f._told_unplugged = True
                self.say(f"{spoken(self.name[f.id], True)} was unplugged: plug it back in and it reconnects by itself.",
                         YELLOW)
            elif getattr(f, "state", "ok") == "ok":
                f._told_unplugged = False

    def mode_test_key(self, f):
        """m: try this camera's other modes for a moment each, in the background, and suggest the cleanest."""
        if not f.usable or self.mode_testing:
            return
        self.mode_testing, self.suggested_mode = True, None
        self.say(f"Testing {spoken(self.name[f.id])}'s modes: about 15 seconds, its picture pauses meanwhile...", YELLOW)

        def run():
            try:
                f.close()
                results = test_modes(f.device_index, BACKENDS[self.cfg_cameras.get("backend", "any")])
                f._start_capture()
                c = self.cfg_cameras
                now = next((r for r in results if r[0][:3] == (int(c["width"]), int(c["height"]),
                                                               str(c.get("fourcc", "MJPG")))), None)
                best = best_mode(results)
                if best is None:
                    self.say("None of its modes gives 1280x720 at 30 fps or more cleanly: keep the one you have", YELLOW)
                elif now and best[:3] == now[1] and abs(best[4] - now[3]) < 0.1:
                    self.say(f"Its current mode is already the cleanest it has (quality {now[3]:.2f}).", GREEN)
                else:
                    self.suggested_mode = best
                    have = any((DATA / "calibration").glob("intrinsics_*.json"))
                    self.say(f"Cleanest: {best[0]}x{best[1]} {best[2]} at {best[5]:.0f} fps (quality {best[4]:.2f}"
                             + (f", now {now[3]:.2f}" if now else "") + "). Press y to use it for every camera"
                             + (": your lens and room calibration are moved to a backup and must be redone." if have
                                else "."), YELLOW)
            except Exception as e:  # noqa: BLE001
                self.say(f"The mode test didn't work: {e}", RED)
            finally:
                self.mode_testing = False
        threading.Thread(target=run, name="mode test", daemon=True).start()

    def apply_mode(self):
        """y after a mode test: write that mode for every camera (the settings have one mode for all), after moving
        any lens and room calibration made at the old mode to a backup (it doesn't fit the new picture)."""
        w, h, fcc, fps = self.suggested_mode[:4]
        cal = DATA / "calibration"
        old = [p for p in cal.glob("intrinsics_*.json")] + [p for p in (cal / "room.json",) if p.is_file()]
        if old:
            dest = DATA / "backups" / f"calibration_before_mode_{time.strftime('%Y%m%d-%H%M%S')}"
            dest.mkdir(parents=True, exist_ok=True)
            for p_ in old:
                shutil.move(str(p_), str(dest / p_.name))
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        for key, value in (("width", w), ("height", h), ("fps", fps), ("fourcc", fcc)):
            text = _set_or_add_key(text, key, value, "set by the setup screen's mode test")
        backup = DATA / "backups" / f"cameras_{time.strftime('%Y%m%d-%H%M%S')}.yaml"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_CONFIG, backup)
        DEFAULT_CONFIG.write_text(text, encoding="utf-8")
        self.suggested_mode = None
        self.say(f"Every camera now uses {w}x{h} {fcc}" + (" (old calibration in my_data\\backups: redo step 2)" if old
                                                         else "") + ". Close this screen and open it again.", GREEN)

    def assign_key(self, f):
        """a: this picture is one of the cameras not found (moved to another USB port with others, so they can't be
        told apart): it takes that camera's name, calibration and turn. a again tries the next missing one."""
        if not f.usable:
            self.say("This camera can't be used", RED)
            return
        if f.id in self.assigned:  # give back the one it had, and try the next
            own_name, own_key, own_turn, m = self.assigned.pop(f.id)
            self.missing.append(m)
            self.name[f.id], self.calib_key[f.id], self.turn[f.id] = own_name, own_key, own_turn
            if f.id in self.order:
                self.order.remove(f.id)
        if not self.missing:
            self.say("No camera is missing: nothing to assign", YELLOW)
            return
        m = self.missing.pop(0)
        slot, name, key, turn = m
        self.assigned[f.id] = (self.name[f.id], self.calib_key[f.id], self.turn[f.id], m)
        self.name[f.id], self.calib_key[f.id], self.turn[f.id] = name, key, turn
        if f.id in self.order:
            self.order.remove(f.id)
        self.order.insert(min(slot, len(self.order)), f.id)
        self.paths_dirty = True
        self.say(f"This is {spoken(name)} now: its name, calibration and turn are kept. Wrong one? Press a again for the "
                 "next. s saves.", GREEN)

    def log_readings(self, f, why):
        """One log line with a camera's readings and verdict (the screen shows them; the log keeps them)."""
        import logging
        st = f.stats
        fl, q = st.flicker_pct(), getattr(f, "quality", ())
        seen = st.frames + st.broken
        sharp = f.sharp()
        logging.getLogger("camera_setup").info(
            "%s readings (%s): %s | fps %.0f | brightness %.0f | noise %.1f | light flicker %s | sharpness %s | "
            "compression %s | damaged %.2f%% | lasting problems: %s | notes: %s", self.name[f.id], why, self.status(f)[0].upper(),
            st.fps(), st.brightness(), getattr(f, "noise", 0.0), "measuring" if fl is None else f"{fl:.1f}%",
            "not judged (too grainy)" if sharp is None else f"{sharp:.1f}",
            f"{float(np.median(q)):.2f}" if len(q) >= 20 else "-", 100.0 * st.broken / seen if seen else 0.0,
            ", ".join(w for w, _ in f.problems()) or "none", ", ".join(w for w, _ in f.notes()) or "none")

    def save_key(self):
        for g in self.found:
            if g.usable and g.id in self.order:
                self.log_readings(g, "saved")
        if not self.order:
            self.say("Use at least one camera first (select it, press space). Two or more are needed to place the cat in 3D", RED)
            return True
        new = [(i, self.name[i]) for i in self.order]
        keys = [self.calib_key[i] for i in self.order]
        self.confirm = None
        by_id = {f.id: f for f in self.found}
        paths = [by_id[i].path for i in self.order]
        try:
            backup = save_settings(DEFAULT_CONFIG, [by_id[i].device_index if hasattr(by_id[i], "device_index") else i
                                                    for i, _ in new], [n for _, n in new],
                                   [self.turn[i] for i in self.order], DATA / "backups", self.backend,
                                   devices=paths if all(paths) else [], exclude=self.exclude, keys=keys)
        except (OSError, ValueError) as e:
            self.say(f"Couldn't save: {e}", RED)
            return True
        self.saved = self.state()
        self.paths_dirty = False
        self.old = new
        notes = calibration_notes(DATA / "calibration", keys, [n for _, n in new])
        self.say(f"Saved {len(new)} cameras to settings\\cameras.yaml (old file backed up to my_data\\backups\\{backup.name})."
                 + (" Note: " + "; ".join(notes) + "." if notes else "") + " Press q to finish", YELLOW if notes else GREEN)
        return True


QUALITY_YELLOW, QUALITY_RED = 1.6, 2.5  # blockiness (capture.camera.jpeg_blocky): measured on the test setup's pictures,
# re-compressed at falling JPEG quality: 1.6 is about quality 75, where fine corners start wandering noticeably more;
# 2.5 about quality 25-30, three times as much, close to frames damaged on the way (3 and up). The test setup's cameras: ~1.1.
MODES_TO_TRY = [(1280, 720, "MJPG", 120), (1280, 720, "MJPG", 60), (1280, 720, "MJPG", 30), (1920, 1080, "MJPG", 60),
                (1920, 1080, "MJPG", 30), (1280, 720, "YUY2", 10), (1280, 960, "MJPG", 60)]


def test_modes(device_index, backend, seconds=2.0, modes=MODES_TO_TRY, log=None):
    """Open the camera in each mode for a moment: what it really gives (size, format, fps) and how compressed the
    picture is. [(asked, got (w, h, fourcc), fps, blockiness)] for the modes that open."""
    out = []
    for w, h, fcc, fps in modes:
        cap = cv2.VideoCapture(device_index, backend)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, fps)
        t0, n, blk = time.monotonic(), 0, []
        while time.monotonic() - t0 < seconds:
            ok, f = cap.read()
            if ok and f is not None:
                n += 1
                if n % 4 == 0:
                    blk.append(jpeg_blocky(f))
        code = int(cap.get(cv2.CAP_PROP_FOURCC))
        got = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
               "".join(chr((code >> 8 * i) & 0xFF) for i in range(4)) if code > 0 else "?")
        cap.release()
        if n:
            out.append(((w, h, fcc, fps), got, n / seconds, float(np.median(blk)) if blk else 9.0))
            if log:
                log.info("mode test: asked %dx%d %s %d fps, got %dx%d %s at %.0f fps, blockiness %.2f", w, h, fcc, fps,
                         *got, n / seconds, out[-1][3])
    return out


def best_mode(results, need_fps=30, min_w=1280, min_h=720):
    """The cleanest mode that keeps at least 1280x720 detail and need_fps, or None: (w, h, fourcc, fps asked,
    blockiness, fps got)."""
    ok = [(blk, -fps, got, asked) for asked, got, fps, blk in results
          if got[0] >= min_w and got[1] >= min_h and fps >= need_fps and (got[0], got[1]) == asked[:2]
          and got[2].upper() == asked[2]]
    if not ok:
        return None
    blk, nfps, got, asked = min(ok)
    return (got[0], got[1], got[2], asked[3], blk, -nfps)


def device_index_now(f):
    """Windows' number for this camera's USB device now (it changes when cameras are unplugged and plugged in
    again): looked up by its device path, else the number it last had."""
    if f.path:
        try:
            paths = [p for _, p in list_devices()]
            if f.path in paths:
                return paths.index(f.path)
        except Exception:  # noqa: BLE001
            pass
    return getattr(f, "device_index", f.id)


COMMON_SIZES = [(3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1280, 960), (1280, 720), (1024, 768),
                (800, 600), (640, 480), (320, 240)]


def mode_problem(cap, c, got):
    """Why a camera can't be used in the configured mode, and what it can do instead, in plain words. Tries the
    common sizes (the driver says which it takes) and, at the wanted size, the other format."""
    want_w, want_h, want_f = int(c["width"]), int(c["height"]), c.get("fourcc", "MJPG")
    sizes = []
    for w, h in COMMON_SIZES:
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            gw, gh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        except cv2.error:
            continue
        if (gw, gh) == (w, h):
            sizes.append((w, h))
    if (want_w, want_h) in sizes:  # the size is there, only not in this format (e.g. uncompressed only: slow)
        return (f"gives {want_w}x{want_h} only uncompressed, not {want_f}: too slow for the tracker. Try another USB "
                "port, or swap this camera")
    biggest = max(sizes, key=lambda s: s[0] * s[1]) if sizes else None
    smaller = biggest is not None and biggest[0] * biggest[1] < want_w * want_h
    got = got.replace(" ?", "")
    return (f"can't do {want_w}x{want_h} (it gives {got}" + (f"; its biggest size is {biggest[0]}x{biggest[1]}"
                                                               if biggest else "") + "). "
            + ("Swap this camera for one that does " + f"{want_w}x{want_h}" if smaller else "Swap this camera")
            + ", or change width and height for all cameras in settings\\cameras.yaml (then redo the lens step)")


def plausible_devices(devs):
    """Is this a real list of cameras? Every video capture device has a USB device path; DirectShow filters (seen
    once when a read went wrong mid-unplug: Frame Rate Converter, Mpeg4s Decoder DMO...) don't. So a list with any
    entry without a path, or implausibly many, is a bad read, and the next scan tries again."""
    return devs is not None and len(devs) <= 16 and all(pth for _, pth in devs)


def startup_note(ui):
    """What to say first about cameras on a new USB port, or not found: (text, colour) or None."""
    if ui.moved:
        return (f"{spoken_list(ui.moved, True)} {'is' if len(ui.moved) == 1 else 'are'} on a new USB port now. Kept "
                f"{'its' if len(ui.moved) == 1 else 'their'} settings: press s to save that.", GREEN)
    if ui.missing:
        names = [m[1] for m in ui.missing]
        return (f"Not found: {spoken_list(names)}. If one is on a new USB port, click its picture here and press a to "
                "make it that camera (its name, calibration and turn are kept).", YELLOW)
    return None


def new_key(taken):
    """A calibration key no camera has had: cam-<6 hex digits>."""
    import secrets
    while True:
        k = "cam-" + secrets.token_hex(3)
        if k not in taken:
            return k


def picker_keys(ui):
    """The picker's keys, for the selected (last clicked) camera."""
    f = ui.found[ui.sel] if ui.found else None
    usable = f is not None and f.usable
    used = usable and f.id in ui.order
    pick = [("Click", "use it / stop using it"), ("Esc", "done")]
    arrange = ([("N", "name it"), ("R", "turn it")] + ([("[ ]", "move in the order")] if used else [])) if usable else []
    camera = []
    if f is not None:
        camera.append(("X", "include it again" if f.excluded else "leave it out"))
    if ui.missing and usable:
        camera.append(("A", "this is the missing camera"))
    if usable and ui.cfg_cameras.get("backend") == "dshow":
        camera.append(("P", "driver settings"))
    return [("Pick", pick), ("The camera you clicked", arrange + camera), ("Window", [("S", "save"), ("?", "help")])]


def grid_keys(ui):
    """The main window's keys."""
    return [("Cameras", [("Click", "see one big"), ("C", "add / remove cameras")]),
            ("Window", [("F", "full screen"), ("S", "save"), ("?", "help"), ("Q", "quit")])]


def big_keys(ui):
    f = ui.found[ui.single]
    used = f.usable and f.id in ui.order
    this = [("Esc", "back"), ("Tab", "next camera"), ("R", "turn"), ("N", "rename"), ("X", "leave it out")]
    if f.usable:
        this.append(("Space", "stop using it" if used else "use it"))
    if not ui.focus_on:
        focus = [("C", "start focus assist")] + ([("O", "skip: sharp enough")] if (f.sharp() or 0) >= FOCUS_SKIP_SHARPNESS
                                                   else [])
    else:
        focus = [("C", "stop"), ("B", "start over"), ("V", "sound: on" if ui.focus_sound else "sound: off")]
    fi = getattr(f, "focus_info", None)
    if f.usable and getattr(f, "focus_verdict", None) != "ring" and (getattr(f, "focus_settable", False) or (fi and fi["autofocus"] == 1 and not fi["can_turn_off"])):
        # only cameras whose driver claims focus control
        focus = [("K", "auto-focus lock (experimental)")] + (
            [("-", ""), ("+", "nudge focus")] if f.focus_value is not None else []) + focus
    view = [("G", "guide lines"), ("F", "full screen"), ("S", "save"), ("?", "help")]
    return [("This camera", this), ("Focus", focus), ("View", view)]


HELP_WIN = "Camera setup: help"
HELP_TEXT = [
    ("The screen", None),
    ("Main window", "the cameras you use, as the tracker will show them, each with its state. Click one: see it big."),
    ("+ ADD / REMOVE", "every camera on this PC (C). Click one to use it or stop using it; the order you pick is kept."),
    ("Yellow CHECKING", "it watches each camera for a minute first: brief things (someone walking past) don't count."),
    ("Yellow FOCUS?", "click it, then START FOCUS ASSIST, or SKIP if its picture is already sharp enough."),
    ("Green CHECKS OK", "the picture checks passed: watched for a minute, no lasting problems, and focused. Done "
                        "when every camera says CHECKS OK."),
    ("Yellow A BIT DARK", "checks passed, but the room is dim and the picture grainy: more light helps it see the "
                          "cat. You can carry on."),
    ("Red frame", "a problem that lasted (most of the last 30 s). Click it: its big view says what, and what to do."),
    ("NOT CONNECTED", "unplugged, or no new pictures. Plug it back in: it reconnects, then is CHECKED again from 0."),
    ("All the time", "the checks keep running while this screen is open: a camera that said CHECKS OK turns red if something goes wrong."),
    ("Big view", "one camera as big as the screen, to aim and focus it, with all its checks under the picture."),
    ("Keys", None),
    ("In the picker", "click: use it / stop using it.  N name it.  R turn it.  [ ] move it in the order.  X leave it out."),
    ("Which is which?", "in the picker, cover a camera with your hand: its picture lights up, \"the one you're covering\"."),
    ("Naming", "N, then click North, East, South or West (the wall it's on), or type a name and press Enter."),
    ("S / Q", "save / quit (asks first if something isn't saved).          F   full screen.   ?   this help."),
    ("In the big view", "BACK (or Esc) goes back.  Tab next camera.  G guide lines.  C starts / stops the focus assist."),
    ("The checks (big view)", None),
    ("fps", "pictures a second. Many cameras give 120 at this size even when asked for 30: that's fine."),
    ("dropped", "pictures that came late or not at all. A few are normal."),
    ("damaged frames", "pictures cut short (blocky at the bottom). Over 1%: not enough USB bandwidth."),
    ("picture quality", "how blocky the compression is. Under 1.6 is good."),
    ("flicker", "the room light pulsing in the picture. Over 1%: set a fixed exposure, or other lights."),
    ("brightness", "0 is black, 255 white. Between 40 and 220 is fine."),
    ("focus", "C in the big view starts the focus assist: turn the ring until the circle is green. Remembered."),
    ("Next", None),
    ("Done here?", "press S to save, then open 2_calibrate_cameras."),
]


def help_page(width=1100):
    """The help window: what's on the screen, the keys, what red means and what each check means."""
    img = np.full((30 * len(HELP_TEXT) + 30, width, 3), 36, np.uint8)
    y = 30
    for key, text in HELP_TEXT:
        if text is None:
            cv2.putText(img, key.upper(), (20, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, YELLOW, 1, cv2.LINE_AA)
        else:
            cv2.putText(img, key, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, YELLOW, 1, cv2.LINE_AA)
            cv2.putText(img, text, (240, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
        y += 30
    return img


def back_button(img, help_box):
    """Draw the white < BACK (Esc) button just left of ? HELP; returns its box. The same place in every view."""
    box = (help_box[0] - 190, help_box[1], help_box[0] - 10, help_box[3])
    cv2.rectangle(img, box[:2], box[2:], WHITE, -1)
    cv2.putText(img, "< BACK (Esc)", (box[0] + 16, box[3] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 2,
                cv2.LINE_AA)
    return box


def help_button(img):
    """Draw the yellow ? HELP button at the top right of img; returns its box (x0, y0, x1, y1)."""
    w = img.shape[1]
    box = (w - 130, 6, w - 10, 40)
    cv2.rectangle(img, box[:2], box[2:], YELLOW, -1)
    cv2.putText(img, "? HELP", (box[0] + 18, box[3] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 2,
                cv2.LINE_AA)
    return box


def colour_bar(width, items):
    """[(text, colour)] side by side on a dark bar, wrapped onto more lines when they don't fit."""
    rows, row, x = [], [], 12
    for t, col in items:
        tw = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0][0] + 30
        if row and x + tw > width - 12:
            rows.append(row)
            row, x = [], 12
        row.append((t, col, x))
        x += tw
    if row:
        rows.append(row)
    bar = np.full((12 + 28 * max(len(rows), 1), width, 3), 30, np.uint8)
    for j, r in enumerate(rows):
        for t, col, x in r:
            outlined_text(bar, t, (x, 30 + 28 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 1, cv2.LINE_AA)
    return bar


def banner(width, text, color):
    """A dark bar with the text on it, wrapped onto more lines when it's wider than the window."""
    lines, line = [], ""
    for word in text.split(" "):
        test = (line + " " + word) if line else word
        if line and cv2.getTextSize(test, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)[0][0] > width - 24:
            lines.append(line)
            line = word
        else:
            line = test
    lines.append(line)
    bar = np.full((12 + 30 * len(lines), width, 3), 30, np.uint8)
    for j, t in enumerate(lines):
        outlined_text(bar, t, (12, 30 + 30 * j), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    return bar


def main():
    ap = argparse.ArgumentParser(description="Camera setup screen")
    ap.add_argument("--max-id", type=int, default=9, help="highest device id to try, when Windows' device list can't be read")
    args = ap.parse_args()
    cfg = load_config()
    log, log_file = start_run("camera_setup", cfg)
    c = cfg["cameras"]
    hold_cameras(log, show=True)  # another tool or the tracker has them: a window says who, and how to close it
    log.info("Finding your cameras ... (a few seconds)")
    log.debug("Looking for cameras that give %dx%d %s, with the %s driver", c["width"], c["height"],
              c.get("fourcc", "MJPG"), c.get("backend", "any"))

    def devices_for(backend):
        return list_devices() if backend == "dshow" else None  # only DirectShow numbers cameras in Windows' order

    found = scan(c, args.max_id, log, devices_for(c.get("backend", "any")))
    backend = None
    if not any(f.usable for f in found):
        for other in [b for b in ("dshow", "msmf") if b != c.get("backend", "any")]:
            log.info("\nNo camera works with the %s driver; trying %s ...", c.get("backend", "any"), other)
            for f in found:
                f.close()
            found = scan({**c, "backend": other}, args.max_id, log, devices_for(other))
            if any(f.usable for f in found):
                backend = other
                break
    if not any(f.usable for f in found):
        log.error("\nNo camera could be used.%s\n"
                  "- Are they plugged in? Try another USB port, or a powered hub.\n"
                  "- Only one program can use a camera at a time: close the old tracker (its stop_tracker.bat),\n"
                  "  fbt, troubleshoot_preview_cameras.bat, and any video call or camera app, then run this again.\n"
                  "- If they show up but can't be used, they may not do %dx%d %s: change cameras.width, height or\n"
                  "  fourcc in settings\\cameras.yaml, or see troubleshoot_find_cameras.bat.",
                  " Found, but not usable: " + "; ".join(f"id {f.id} {f.name}: {'excluded' if f.excluded else f.reason}"
                                                         for f in found) if found else "",
                  c["width"], c["height"], c.get("fourcc", "MJPG"))
        for f in found:
            f.close()
        return 1
    devs = [(f.name, f.path) for f in found] if all(f.path for f in found) else None
    old_ids, problems = resolve_ids({**c, **({"backend": backend} if backend else {})}, log, devs) if devs else (None, {})
    if old_ids is not None:  # a camera that wasn't found is missing, not whatever device has its old number now
        old_ids = [-1 if slot in problems else i for slot, i in enumerate(old_ids)]
    log.info("Found %d camera(s)%s.", sum(1 for f in found if f.usable),
             "" if all(f.usable or f.excluded for f in found) else " (some can't be used: see above)")
    ui = Setup(found, cfg, backend, old_ids)
    try:  # the speed check only matters with the experimental lower frame rate on
        from cat_tracker import settings as cat_settings
        ui.speed_check = str(cat_settings.load().get("cameras", {}).get("fps_full", "")) != ""
    except Exception:  # noqa: BLE001
        ui.speed_check = False
    if ui.speed_check:
        ui.speed_queue = [f.id for f in found if f.usable]
    usable = {f.id for f in found if f.usable}
    missing = [f"{n} (id {i})" for i, n in ui.old if i not in usable]
    skipped = [f.name for f in found if f.excluded]
    if missing:
        ui.say("From your settings, not found now: " + ", ".join(missing) + ". Plugged in? Wave at each camera to see"
               " which tile it is.", YELLOW)
    elif backend:
        ui.say(f"Found {len(found)} camera(s) with the {backend} camera driver (the settings' one gave no picture);"
               " saving switches the settings to it. Wave at a camera to see which tile it is.", YELLOW)
    else:
        ui.say(f"Found {len(usable)} camera(s)" + (f"; not opened: {', '.join(skipped)}" if skipped else "")
               + ". Wave at a camera to see which tile it is. Aim: floor in the lower two thirds, heads in the top third.")
    note = startup_note(ui)
    if note:
        ui.say(*note)
    from tools.window import open_window, set_fullscreen, window_size
    open_window(WIN)  # maximised on the main monitor; can be moved and resized
    full = [False]

    def show():
        if ui.fullscreen != full[0]:  # f: true fullscreen, on whichever monitor the window is
            set_fullscreen(WIN, ui.fullscreen)
            full[0] = ui.fullscreen
        ui.screen = window_size(WIN, ui.screen)  # the window's real size: the picture fills it, centred
        cv2.imshow(WIN, ui.present())
        if getattr(ui, "help_open", False):
            if help_shown[0]:
                try:
                    if cv2.getWindowProperty(HELP_WIN, cv2.WND_PROP_VISIBLE) < 1:  # closed with its X
                        ui.help_open = help_shown[0] = False
                        return
                except cv2.error:
                    ui.help_open = help_shown[0] = False
                    return
            cv2.imshow(HELP_WIN, help_page())
            help_shown[0] = True
        elif help_shown[0]:
            try:
                cv2.destroyWindow(HELP_WIN)
            except cv2.error:
                pass
            help_shown[0] = False

    help_shown = [False]
    cv2.setMouseCallback(WIN, lambda ev, x, y, *_: ui.click(x, y) if ev == cv2.EVENT_LBUTTONDOWN else None)
    try:
        from tools.voice import Voice
        ui.voice = Voice(volume=float((cfg.get("calibration") or {}).get("voice_volume", 0.8)),
                         prerender=[FOCUS_FIND, FOCUS_FOUND, FOCUS_HINT, FOCUS_BOARD_FOUND,
                                    "Focus sound on"])  # the focus meter's few spoken lines
    except Exception as e:  # noqa: BLE001  (no voice is fine here: the screen says it all too)
        log.warning("No voice for the focus meter: %s", e)
    stop_scan = threading.Event()

    def scanner():  # off the frame loop: the device list takes a few ms to a few tens of ms to read
        while not stop_scan.wait(RESCAN_EVERY_S):
            try:
                ui.rescan()
            except Exception as e:  # noqa: BLE001
                log.warning("Couldn't look for cameras: %s", e)
    threading.Thread(target=scanner, name="camera rescan", daemon=True).start()
    try:
        while True:
            if ui.voice:
                ui.voice.tick()
            ui.apply_rescan()
            show()
            code = cv2.waitKeyEx(30)
            if code != -1 and not ui.key(code):
                break
            if ui.speed_queue and ui.typing is None:  # one camera at a time, about 2 s each, with a message up
                i = ui.speed_queue.pop(0)
                f = next((g for g in ui.found if g.id == i and g.usable), None)
                if f is not None:
                    keep = ui.message, ui.message_color
                    ui.say(f"Checking whether {ui.name[i]} can run at the tracker's lower speed ({AUTO_FPS} fps) ...", YELLOW)
                    show()
                    cv2.waitKey(1)
                    real = f.speed_check()
                    log.info("%s (id %d): asked %d fps, gives %s", ui.name[i], i, AUTO_FPS,
                             "nothing" if real is None else f"{real:.0f}")
                    ui.say(*keep)
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:  # closed with the window's X
                if ui.dirty:
                    log.warning("Closed without saving the last changes")
                break
    finally:
        stop_scan.set()
        for f in ui.found:
            f.close()
        if ui.voice:
            ui.voice.close()
        cv2.destroyAllWindows()
    if ui.order:
        for g in ui.found:
            if g.usable and g.id in ui.order:
                ui.log_readings(g, "at exit")
        log.info("Cameras in use, in order: %s", ", ".join(f"{ui.name[i]} (id {i}, {TURN_LABEL[ui.turn[i]]})"
                                                           for i in ui.order))
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
