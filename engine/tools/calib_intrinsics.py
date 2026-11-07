"""Lens calibration wizard: walks through every camera in turn, and talks you through each one.

Run from engine/ (2_calibrate_cameras/1_lens_calibration.bat does this):
  python -m tools.calib_intrinsics                     every camera in settings/cameras.yaml, one after another
  python -m tools.calib_intrinsics --cam north         just that camera (name from cameras.names, or number)
  python -m tools.calib_intrinsics --cam north --from-dir   recalibrate from the frames saved last time
  --quiet                                              no voice or beeps
  --practice                                           a rehearsal of the flow for testing: 4 views per camera, in
                                                       my_data/practice (wiped each time); real results untouched

For each camera: a big window of that camera (fullscreen; f toggles). A camera to do starts capturing straight away,
announced by voice. One that's already GOOD is skipped after a short announcement (r redoes it), and one with views
saved from an unfinished run finishes with them (r starts over); s skips, space goes on at once, q stops. m mirrors
the picture like a selfie camera, if moving the board feels backwards; it's off by default, remembered per camera for
the session, and display only. Hold the board up to the camera: the next area to cover is lit up with an arrow from
the board to it, and a voice says which way to move, in your own left and right as you face the camera ("Move left",
"Higher", "Tilt the board", "Hold still"), with a beep that speeds up as the board gets there and a chime for each view. A view is captured when the board is held
still and differs enough from earlier views; green cells are covered. It calibrates by itself at the target number of
views, or once every area is covered and calibration.intrinsics.finish_when_covered views are in; then it moves on to
the next camera. c finishes the camera early (8 views or more), space forces a capture. v turns the voice and beeps off and on.
Result: my_data/calibration/intrinsics_<name>.json, plus the frames in my_data/calibration/intrinsics/<name>/.
"""

import argparse
import json
import time

import cv2
import numpy as np

from calibration import intrinsics as intr
from calibration.board import make_board
from capture.camera import (Camera, camera_keys, camera_names, camera_slot, outlined_text, resolve_ids, rotations,
                            spoken)
from core.config import DATA, get, load_config, resolve_path
from core.runlog import start_run
from tools.voice import Voice

WIN = "Lens calibration"
FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN, YELLOW, WHITE, RED, CYAN = (80, 220, 80), (0, 210, 255), (245, 245, 245), (80, 80, 255), (255, 220, 0)
GRID = (8, 6)  # the coverage grid, as calibration.intrinsics.coverage uses
MIN_VIEWS = 8  # fewest views a camera can be calibrated (or finished early with c / q-y) from
PRACTICE = False  # --practice: the top bar says so on every screen


def novelty(view, accepted):
    """Smallest mean corner distance to any accepted view sharing corners (large = new pose)."""
    best = np.inf
    for a in accepted:
        common, ia, ib = np.intersect1d(view[2], a[2], return_indices=True)
        if len(common) < 4:
            continue
        best = min(best, float(np.mean(np.linalg.norm(view[1][ia] - a[1][ib], axis=1))))
    return best


def solve_lens(log, views, size, ic, cam_name=""):
    """Calibrate, and check for a printer stretch: the board's height/width is fitted along with the lens. A small
    one-way stretch (at least stretch_correct_above) is corrected; a big one (stretch_reprint_above) means reprint.
    Returns the result, with board_stretch, stretch_corrected and status ("GOOD" / "REDO" / "CHECK YOUR PRINT")."""
    cov, _ = intr.coverage(views, size)
    log.info("Calibrating %s from %d views, %.0f%% of the image covered", cam_name, len(views), 100 * cov)
    models = ic.get("models", ["fisheye", "rational"])
    factor = float(ic.get("outlier_factor", 3.0))
    res = intr.calibrate(views, size, models=models, outlier_factor=factor, log=log)
    stretch, corrected = 1.0, False
    correct_above = float(ic.get("stretch_correct_above", 0.005))
    reprint_above = float(ic.get("stretch_reprint_above", 0.03))
    if correct_above > 0:
        stretch, rms_as_printed, rms_fit = intr.fit_stretch(views, size, res["model"], factor,
                                                            limit=max(0.05, 1.5 * reprint_above))
        log.info("  board height/width as printed: %.4f (RMS %.3f px as designed, %.3f px fitted)", stretch,
                 rms_as_printed, rms_fit)
        if correct_above <= abs(stretch - 1) < reprint_above:
            res = intr.calibrate(intr.stretch_views(views, stretch), size, models=models, outlier_factor=factor,
                                 log=log)
            corrected = True
            log.info("  The printout is stretched %.1f%% one way: corrected for it", 100 * abs(stretch - 1))
    good = res["rms_px"] <= float(ic.get("max_rms_px", 0.8)) and cov >= float(ic.get("min_coverage", 0.6))
    status = "CHECK YOUR PRINT" if abs(stretch - 1) >= reprint_above else "GOOD" if good else "REDO"
    res.update(board_stretch=round(stretch, 5), stretch_corrected=corrected, status=status, coverage=cov)
    log.info("\n%s: %s model, RMS %.3f px, coverage %.0f%%  ->  %s", cam_name, res["model"], res["rms_px"], 100 * cov,
             "FIT GOOD" if status == "GOOD" else status if status != "REDO" else "REDO (want RMS <= %.2f px and coverage >= %.0f%%)" % (
                 float(ic.get("max_rms_px", 0.8)), 100 * float(ic.get("min_coverage", 0.6))))
    return res


def run_calibration(log, views, size, ic, out_path, cam_name, device_id):
    res = solve_lens(log, views, size, ic, cam_name)
    intr.save(out_path, cam_name, device_id, size, res)
    log.info("Saved %s", out_path)
    return res, res["status"] == "GOOD"


# ---- guidance: where to put the board next, in the words of someone facing the camera ---------------------------

def to_display(pt, size, rotation, mirror):
    """A raw-frame pixel (x, y) to where it is drawn: turned by cameras.rotate, then mirrored if asked."""
    x, y = float(pt[0]), float(pt[1])
    w, h = size
    if rotation == cv2.ROTATE_90_CLOCKWISE:
        x, y, w, h = h - 1 - y, x, h, w
    elif rotation == cv2.ROTATE_90_COUNTERCLOCKWISE:
        x, y, w, h = y, w - 1 - x, h, w
    elif rotation == cv2.ROTATE_180:
        x, y = w - 1 - x, h - 1 - y
    if mirror:
        x = w - 1 - x
    return x, y


def direction(board, target, size, rotation, mirror, near_px=60):
    """Which way to move the board to get from board to target (raw-frame pixels): "left", "right", "higher",
    "lower", or None when it's there, in the picture turned by cameras.rotate and mirrored if mirror. With
    mirror=True that's the person's own left and right as they stand facing the camera holding the board (the camera
    sees them mirrored); the wizard speaks it that way whatever the screen shows."""
    bx, by = to_display(board, size, rotation, mirror)
    tx, ty = to_display(target, size, rotation, mirror)
    dx, dy = tx - bx, ty - by
    if np.hypot(dx, dy) < near_px:
        return None
    if abs(dx) >= abs(dy):
        return "left" if dx < 0 else "right"
    return "higher" if dy < 0 else "lower"


def cell_centre(cell, size):
    gx, gy = cell
    return ((gx + 0.5) * size[0] / GRID[0], (gy + 0.5) * size[1] / GRID[1])


def next_target(hit, board, size):
    """The uncovered grid cell nearest the board (raw pixels), or None when every cell is covered."""
    free = np.argwhere(~hit)  # (gy, gx)
    if len(free) == 0:
        return None
    centres = np.array([cell_centre((gx, gy), size) for gy, gx in free])
    k = int(np.argmin(np.linalg.norm(centres - np.asarray(board, float), axis=1)))
    return int(free[k][1]), int(free[k][0])


POSE_PROMPTS = ["Tilt the board to one side", "Tilt the board up or down", "Bring it closer", "Move it further away"]
ALL_COVERED = "Every area is covered. Now tilt the board a few different ways, and hold each one still."


# ---- drawing -----------------------------------------------------------------------------------------------------

def big_text(img, text, y, scale, color, centre=True):
    (w, h), _ = cv2.getTextSize(text, FONT, scale, max(2, int(scale * 2)))
    x = (img.shape[1] - w) // 2 if centre else 20
    outlined_text(img, text, (x, y), FONT, scale, color, max(2, int(scale * 2)), cv2.LINE_AA)


def screen_size():
    try:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:  # noqa: BLE001
        return 1920, 1080


def fit(img, screen):
    s = min(screen[0] / img.shape[1], screen[1] / img.shape[0])
    return cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_LINEAR)


class Window:
    """The wizard's window: opens maximised on the main monitor (it can be moved and resized), every picture fitted
    and centred to the window's real size, so it reads from across the room on any monitor. f: true fullscreen."""

    def __init__(self, title=WIN):
        from tools.window import open_window
        self.title = title
        self.full = False
        self.mirror = False  # per camera, set by the caller; display only
        self.screen = screen_size()
        open_window(title)
        from tools.window import quit_when_closed
        quit_when_closed(title)  # its X quits, as q does

    def toggle_full(self):
        from tools.window import set_fullscreen
        self.full = not self.full
        set_fullscreen(self.title, self.full)

    def show(self, img):
        from tools.window import fit_into, window_size
        size = window_size(self.title, self.screen)
        cv2.imshow(self.title, fit_into(img, size)[0])


def draw(frame, hit, size, rotation, mirror, board=None, target=None, corners=None, flash=False):
    """The camera picture as shown: coverage grid, the target cell lit up, an arrow from the board to it."""
    disp = frame.copy()
    gw, gh = GRID
    for gy in range(gh):
        for gx in range(gw):
            x0, y0 = gx * size[0] // gw, gy * size[1] // gh
            x1, y1 = (gx + 1) * size[0] // gw, (gy + 1) * size[1] // gh
            if hit[gy, gx]:
                disp[y0:y1, x0:x1, 1] = np.clip(disp[y0:y1, x0:x1, 1].astype(np.int16) + 18, 0, 255)
                cv2.rectangle(disp, (x0 + 4, y0 + 4), (x1 - 4, y1 - 4), GREEN, 2)
            else:
                cv2.rectangle(disp, (x0, y0), (x1, y1), (90, 90, 90), 1)
    if target is not None:  # the next area: a thin outline and a light fill, so the picture stays visible
        gx, gy = target
        x0, y0 = gx * size[0] // gw, gy * size[1] // gh
        x1, y1 = (gx + 1) * size[0] // gw, (gy + 1) * size[1] // gh
        over = disp.copy()
        cv2.rectangle(over, (x0, y0), (x1, y1), CYAN, -1)
        disp = cv2.addWeighted(over, 0.18, disp, 0.82, 0)
        cv2.rectangle(disp, (x0, y0), (x1, y1), CYAN, 3)
    if corners is not None:
        for p in corners:
            cv2.circle(disp, (int(p[0]), int(p[1])), 3, YELLOW, -1)
    if rotation is not None:
        disp = cv2.rotate(disp, rotation)
    if mirror:
        disp = cv2.flip(disp, 1)
    if board is not None and target is not None:
        start = arrow_start(board, corners, cell_centre(target, size), size, rotation, mirror)
        if start is not None:  # from the edge of the board, never across it
            t = tuple(int(v) for v in to_display(cell_centre(target, size), size, rotation, mirror))
            cv2.arrowedLine(disp, start, t, (0, 0, 0), 9, cv2.LINE_AA, tipLength=0.12)
            cv2.arrowedLine(disp, start, t, CYAN, 4, cv2.LINE_AA, tipLength=0.12)
    if flash:
        disp = cv2.addWeighted(disp, 0.7, np.full_like(disp, 255), 0.3, 0)
    return disp


def arrow_start(board, corners, target, size, rotation, mirror):
    """Where the arrow to the target leaves the board's box (display pixels), or None if the target is inside it."""
    pts = [to_display(p, size, rotation, mirror) for p in (corners if corners is not None and len(corners) else [board])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = to_display(board, size, rotation, mirror)
    tx, ty = to_display(target, size, rotation, mirror)
    if x0 <= tx <= x1 and y0 <= ty <= y1:
        return None
    dx, dy = tx - cx, ty - cy
    s = min((x1 - cx) / dx if dx > 0 else (x0 - cx) / dx if dx < 0 else np.inf,
            (y1 - cy) / dy if dy > 0 else (y0 - cy) / dy if dy < 0 else np.inf)
    s = min(max(s, 0.0), 1.0)
    gap = 25.0 / max(np.hypot(dx, dy), 1e-6)  # a little clear of the outer corners, which sit inside the board's edge
    s = min(s + gap, 1.0)
    return int(cx + s * dx), int(cy + s * dy)


def bar(width, lines):
    """A dark bar of big outlined text, [(text, scale, colour)], one line under another."""
    s = width / 1280
    heights = [int(scale * s * 34) + int(18 * s) for _, scale, _ in lines]
    out = np.full((sum(heights) + int(16 * s), width, 3), 25, np.uint8)
    y = int(8 * s)
    for (text, scale, color), h in zip(lines, heights):
        y += h
        if text:
            big_text(out, text, y - int(10 * s), scale * s, color)
    return out


def overlay(disp, name, line1, line2, line3, color2=WHITE, keys=""):
    """The camera picture between two bars of big text, so nothing large ever covers the picture: the camera,
    progress and mirror state on top; the one instruction and the keys underneath."""
    w = disp.shape[1]
    top = bar(w, ([("PRACTICE RUN, nothing is saved", 0.9, YELLOW)] if PRACTICE else []) + [(name, 1.4, WHITE)]
              + ([(line1, 1.0, WHITE)] if line1 else []) + ([(line3, 0.75, WHITE)] if line3 else []))
    bottom = bar(w, [(line2 or "", 2.0, color2)])
    if keys:  # the keys as keycaps, under the instruction
        from tools.keycaps import key_bar, keys_from_text
        bottom = np.vstack([bottom, key_bar(w, keys_from_text(keys), scale=0.62 * w / 1280, bg=25)])
    return np.vstack([top, disp, bottom])


KEYS = "f fullscreen   v voice   q quit"


def mirror_hint(win):
    return "M: mirror the picture (if moves feel backwards)   Mirror: " + ("ON" if win.mirror else "off")


# ---- one camera --------------------------------------------------------------------------------------------------

def wait_for_camera(cam, name, win, voice, size):
    """A camera that isn't there yet: say so, and wait until it is ("there"), or s ("skip") or q ("quit")."""
    from capture.camera import say_camera_events
    while True:
        say_camera_events([cam], voice)
        voice.tick()
        if cam.state == "ok":
            item = cam.latest(rotated=False)
            if item is not None and item[2] != -1:
                return "there"
        item = cam.latest(rotated=False)
        disp = item[0] if item is not None else np.zeros((size[1], size[0], 3), np.uint8)
        win.show(overlay(disp, name, "", f"{name}: not found yet, waiting for it", "", YELLOW,
                         "s skip this camera   q quit"))
        key = cv2.waitKey(100) & 0xFF
        if key == ord("s"):
            return "skip"
        if key in (ord("q"), 27):
            return "quit"


def is_good(path, ic):
    """A lens calibration already saved and under max_rms_px (coverage was checked when it was made)."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d["rms_px"] <= float(ic.get("max_rms_px", 0.8)) and d.get("status", "GOOD") == "GOOD"
    except (OSError, ValueError, KeyError):
        return False


def saved_views(frame_dir, detector, board, min_corners):
    """The usable views in the frames an earlier run saved (e.g. one stopped with q)."""
    views = []
    for path in sorted(frame_dir.glob("*.png")):
        v = intr.detect(detector, board, cv2.imread(str(path)))
        if v is not None and intr.usable(board, v, min_corners):
            views.append(v)
    return views


def start_screen(cam, name, k, n, good, nxt, win, voice, size, saved=0, start_after=4.0):
    """Announce the camera, then go on by itself once the announcement has finished and start_after seconds have
    passed: start capturing, or for a camera that's already GOOD skip it, or with views saved from last time finish
    with them. Keys during the countdown: space/Enter now, s skip, r redo / start over, q quit.
    Returns "start", "resume", "skip" or "quit"."""
    if good:
        auto, label = "skip", "already FIT GOOD: skipping"
        voice.say(f"{spoken(name, True)} is already done, so I'll skip it. Press R to redo it.", force=True)
    elif saved:
        auto, label = "resume", f"finishing with the {saved} views saved last time"
        voice.say(f"{spoken(name, True)}: finishing with the {saved} views saved last time. Press R to start over instead.",
                  force=True)
    else:
        return "start"  # nothing to decide: capture straight away (only views with the board in them count)
    deadline = time.monotonic() + start_after
    while True:
        now = time.monotonic()
        item = cam.latest(rotated=False)
        frame = item[0] if item is not None else np.zeros((size[1], size[0], 3), np.uint8)
        disp = draw(frame, np.zeros(GRID[::-1], bool), size, cam.rotation, win.mirror)
        left = max(0, int(np.ceil(deadline - now)))
        keys = "s skip   r redo" if good else "s skip   r start over" if saved else "s skip"
        msg = f"{label.capitalize()} in {left} s" if left else label.capitalize() + " ..."
        disp = overlay(disp, f"{name}  (camera {k} of {n})", "Lens calibration", msg,
                       mirror_hint(win) + (f"     Next: {nxt}" if nxt else ""), GREEN if good else YELLOW,
                       keys + "   space now   " + KEYS)
        win.show(disp)
        voice.tick(now)
        key = cv2.waitKey(15) & 0xFF
        if key in (ord("q"), 27):
            return "quit"
        if key == ord("s"):
            return "skip"
        if key == ord("r"):
            return "start"
        if key in (ord(" "), 13):
            return auto
        handle_view_keys(key, win, voice)
        # go on by itself once the announcement has been spoken and the countdown is over
        if now >= deadline and voice.pending is None and now >= voice.busy_until:
            return auto


def handle_view_keys(key, win, voice):
    if key == ord("f"):
        win.toggle_full()
    elif key == ord("m"):
        win.mirror = not win.mirror
        voice.say("Mirror on" if win.mirror else "Mirror off", force=True)
    elif key == ord("v"):
        voice.on = not voice.on
        voice.say("Voice on", force=True)


def hit_now(views, size):
    return intr.coverage(views, size)[1] if views else np.zeros(GRID[::-1], bool)


def wizard(cam, name, size, detector, board, ic, frame_dir, win, voice, log, first=False):
    """Capture views until the target, then calibrate. Returns the list of views, or None if stopped (q)."""
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.png"):
        old.unlink()  # a new session replaces the previous frames
    target = int(ic.get("target_views", 40))
    finish_n = int(ic.get("finish_when_covered", 30))  # every area covered and this many views: done early
    min_corners = int(ic.get("min_corners", 8))
    still_px = float(ic.get("still_px", 1.5))
    novelty_px = float(ic.get("novelty_px", 40))
    views, last, last_seq, flash_until, pose_k = [], None, -1, 0.0, 0
    voice.say(f"Next is {spoken(name)}. Hold Board A up to it."
              + (" If moving the board feels backwards, press M to mirror the picture." if first else ""), force=True)
    board_seen = time.monotonic()  # the reminder waits until the board has been missing a while
    said_way_at = -1e9  # directions at most every 4 s: the beeps guide moment to moment, the voice nudges
    told_all_covered = False
    quitting = False
    while True:
        from capture.camera import say_camera_events
        say_camera_events([cam], voice)  # unplugged / back
        item = cam.latest(rotated=False)
        if item is None or item[2] == last_seq:
            key = cv2.waitKey(5) & 0xFF
            if key in (ord("q"), 27):
                return None
            handle_view_keys(key, win, voice)
            continue
        frame, _, last_seq = item
        now = time.monotonic()
        voice.tick(now)
        if quitting:  # q with enough views: y calibrates with them, n stops (the views stay saved)
            disp = overlay(draw(frame, hit_now(views, size), size, cam.rotation, win.mirror), name,
                           f"{len(views)} views so far", f"Calibrate with these {len(views)} views?  y / n", "", YELLOW,
                           "y calibrate   n stop (they stay saved for next time)")
            win.show(disp)
            key = cv2.waitKey(15) & 0xFF
            if key == ord("y"):
                return views
            if key in (ord("n"), 27, ord("q")):
                return None
            continue
        v = intr.detect(detector, board, frame)
        if v is not None:
            board_seen = now
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            if len(views) < MIN_VIEWS:
                return None
            quitting = True
            voice.say(f"Calibrate with the {len(views)} views you have? Press Y for yes, N for no.", now, force=True)
            continue
        handle_view_keys(key, win, voice)
        force = key == ord(" ")
        cov, hit = intr.coverage(views, size) if views else (0.0, np.zeros(GRID[::-1], bool))
        covered = bool(hit.all())  # then the last views just need different tilts and distances
        if covered and not told_all_covered:
            told_all_covered = True
            voice.say(ALL_COVERED, now, force=True)
        centre = goal = None
        instruction, color = ("Hold Board A up and tilt it" if covered else "Hold Board A up to the camera"), YELLOW
        if v is not None and intr.usable(board, v, min_corners):
            centre = v[1].mean(axis=0)
            still = False
            if last is not None:
                common, ia, ib = np.intersect1d(v[2], last[2], return_indices=True)
                still = len(common) >= min_corners and np.mean(np.linalg.norm(v[1][ia] - last[1][ib], axis=1)) < still_px
            new = novelty(v, views) > novelty_px
            if (still and new) or force:  # the capture rule, unchanged
                views.append(v)
                cv2.imwrite(str(frame_dir / f"{len(views):03d}.png"), frame)
                flash_until = now + 0.25
                log.info("view %d: %d corners", len(views), len(v[2]))
                voice.click()  # a chime marks every capture; the voice goes straight on to the next direction
                said_way_at = -1e9
                cov, hit = intr.coverage(views, size)
                instruction, color = "Captured!", GREEN
            else:
                goal = next_target(hit, centre, size)
                # spoken: your own left and right as you hold the board up facing the camera, which is the camera
                # picture mirrored, whatever the M toggle shows. On screen: the arrow and the box, as displayed.
                way = (direction(centre, cell_centre(goal, size), size, cam.rotation, mirror=True)
                       if goal is not None else None)
                if goal is not None and way is not None:
                    instruction = "Move the board to the blue box"
                    if now - said_way_at >= 4 and voice.say(
                            {"left": "Move left", "right": "Move right", "higher": "Higher", "lower": "Lower"}[way], now):
                        said_way_at = now
                    d = np.linalg.norm(np.asarray(cell_centre(goal, size)) - centre)
                    voice.park(1.0 - d / np.hypot(*size), now)
                elif not new:
                    prompt = POSE_PROMPTS[pose_k % len(POSE_PROMPTS)]
                    instruction = prompt + (f"  ({max(finish_n - len(views), 1)} more)" if covered else "")
                    if voice.say(prompt, now):
                        pose_k += 1
                else:
                    instruction, color = "Hold still", GREEN
                    voice.say("Hold still", now)
            last = v
        elif v is not None:
            instruction = "Bring the board closer, facing the camera"
            voice.say("Bring the board closer, facing the camera", now)
            last = None
        else:
            if now - board_seen >= 10:  # only after 10 s without the board, never for a brief drop-out
                voice.say("Hold Board A up and tilt it" if covered else "Hold Board A up to the camera", now)
            last = None
        disp = draw(frame, hit, size, cam.rotation, win.mirror, centre, goal,
                    v[1] if v is not None else None, now < flash_until)
        progress = (f"{len(views)} / {finish_n} views   all areas covered: now tilt it" if covered
                    else f"{len(views)} / {target} views   {cov * 100:.0f}% covered")
        disp = overlay(disp, name, progress, instruction, mirror_hint(win),
                color, "space capture   c finish now   " + KEYS)
        win.show(disp)
        if (len(views) >= target or key == ord("c") or (covered and len(views) >= finish_n)) and len(views) >= MIN_VIEWS:
            return views


def main():
    ap = argparse.ArgumentParser(description="Lens calibration wizard")
    ap.add_argument("--config")
    ap.add_argument("--cam", help="just this camera: a name from cameras.names, or its number from 1")
    ap.add_argument("--from-dir", action="store_true", help="recalibrate --cam from saved frames, no camera needed")
    ap.add_argument("--quiet", action="store_true", help="no voice or beeps")
    ap.add_argument("--practice", action="store_true", help="rehearse the flow: 4 views per camera, nothing real saved")
    args = ap.parse_args()
    cfg = load_config(args.config)
    ic = get(cfg, "calibration.intrinsics", {}) or {}
    names = camera_names(cfg)
    keys = camera_keys(cfg)  # what the results are filed under; the names are only shown
    slots = [camera_slot(cfg, args.cam)] if args.cam else list(range(len(names)))
    log, log_file = start_run("calib_intrinsics" + (f"_{names[slots[0]]}" if args.cam else ""), cfg)
    board = make_board(get(cfg, "calibration.boards.small"))
    bcfg = get(cfg, "calibration.boards.small")
    board_cm = (bcfg["squares"][0] * bcfg["square_mm"] / 10, bcfg["squares"][1] * bcfg["square_mm"] / 10)
    detector = intr.make_detector(board, ic)
    data_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    c = cfg["cameras"]
    size = (int(c["width"]), int(c["height"]))
    if args.practice:
        if args.from_dir:
            log.error("--practice can't be used with --from-dir")
            return 1
        global MIN_VIEWS, PRACTICE
        import shutil
        data_dir = DATA / "practice"  # its own throwaway folder: the real calibration is never read or written
        shutil.rmtree(data_dir, ignore_errors=True)
        data_dir.mkdir(parents=True)
        ic = dict(ic, target_views=4, finish_when_covered=4)
        MIN_VIEWS, PRACTICE = 4, True
        log.info("PRACTICE RUN in %s: 4 views per camera, nothing real is read or saved", data_dir)

    if args.from_dir:
        if not args.cam:
            log.error("--from-dir needs --cam")
            return 1
        name, key = names[slots[0]], keys[slots[0]]
        frame_dir = data_dir / "intrinsics" / key
        views = []
        for p in sorted(frame_dir.glob("*.png")):
            v = intr.detect(detector, board, cv2.imread(str(p)))
            if v is not None and intr.usable(board, v, int(ic.get("min_corners", 8))):
                views.append(v)
        log.info("%d usable views in %s", len(views), frame_dir)
        if len(views) < 8:
            log.error("Need at least 8 views")
            return 1
        _, good = run_calibration(log, views, size, ic, data_dir / f"intrinsics_{key}.json", name, c["ids"][slots[0]])
        log.info("Log: %s", log_file)
        return 0 if good else 1

    ids, problems = resolve_ids(cfg, log)
    target = int(ic.get("target_views", 40))
    known = (["Move left", "Move right", "Higher", "Lower", "Hold still", "Hold Board A up to the camera",
              "Bring the board closer, facing the camera", "Mirror on", "Mirror off", "Voice on",
              "Calculating. Please wait.", "Hold Board A up and tilt it", ALL_COVERED] + POSE_PROMPTS)
    voice = Voice(on=not args.quiet and bool(ic.get("voice", True)), volume=float(get(cfg, "calibration.voice_volume", 0.8)),
                  prerender=known)
    from core.single import hold_cameras
    hold_cameras(log, say=lambda t: (voice.say(t, force=True), voice.flush()), show=True)  # a window says who has them
    win = Window()
    if PRACTICE:
        voice.say("Practice run. Nothing is saved.", force=True)
    results, lines = {}, []
    autofocus_on = set()  # cameras whose autofocus was on: their result is marked at the end
    mirrored = {}  # mirror view per camera, for this session
    try:
        for k, slot in enumerate(slots):
            name = names[slot]
            out_path = data_dir / f"intrinsics_{keys[slot]}.json"
            cam = Camera(slot, ids[slot], c, rotations(cfg)[slot])
            fresh = True
            if slot in problems:  # not there (yet): wait for it, it joins by itself (s skips it, q quits)
                log.warning(problems[slot])
                cam.state = "missing"
                cam.start()
                waited = wait_for_camera(cam, name, win, voice, size)
                if waited != "there":
                    cam.stop()
                    results[name] = "not found" if waited == "skip" else "stopped"
                    if waited == "quit":
                        break
                    continue
                fresh = False
            try:
                if fresh:
                    cam.open()
                    cam.start()
                nxt = names[slots[k + 1]] if k + 1 < len(slots) else None
                if cam.autofocus_stuck:  # the setup screen found its autofocus can't be switched off
                    log.warning("%s: its autofocus can't be switched off: the lens result may not stay right", name)
                    voice.say(f"{spoken(name, True)}'s autofocus can't be switched off. Its lens calibration may not "
                              "stay right, and tracking may drift.", force=True)
                    autofocus_on.add(name)
                win.mirror = mirrored.get(name, False)
                frame_dir = data_dir / "intrinsics" / keys[slot]
                done = is_good(out_path, ic)
                saved = [] if done else saved_views(frame_dir, detector, board, int(ic.get("min_corners", 8)))
                saved = saved if len(saved) >= MIN_VIEWS else []
                choice = start_screen(cam, name, k + 1, len(slots), done, nxt, win, voice, size, len(saved),
                                      float(ic.get("start_after_s", 4)))
                if choice == "quit":
                    results[name] = "stopped"
                    break
                if choice == "skip":
                    results[name] = "FIT GOOD (kept)" if is_good(out_path, ic) else "skipped"
                    continue
                views = saved if choice == "resume" else wizard(cam, name, size, detector, board, ic, frame_dir, win,
                                                                voice, log, first=k == 0)
                if views is None:
                    results[name] = "stopped"
                    break
                voice.say("Calculating. Please wait.", force=True)
                voice.flush()  # said before the calculation blocks the loop
                disp = overlay(np.zeros((size[1], size[0], 3), np.uint8), name, "", "Calculating ...", "", YELLOW)
                win.show(disp)
                cv2.waitKey(1)
                if PRACTICE:  # 4 views can't calibrate a lens; the point is the flow
                    good = True
                    log.info("%s: practice, %d views (not calibrated)", name, len(views))
                else:
                    res, good = run_calibration(log, views, size, ic, out_path, name, ids[slot])
                status = "GOOD" if PRACTICE else res["status"]
                results[name] = ("FIT GOOD (practice)" if PRACTICE else "FIT GOOD") if good else status
                said = f"{spoken(name, True)} is done." if good else f"{spoken(name, True)} needs another try."
                if not PRACTICE and res.get("stretch_corrected"):
                    said = "Your printout is slightly stretched. I've corrected for it. " + said
                    if good:
                        results[name] = "FIT GOOD (print stretch corrected)"
                if status == "CHECK YOUR PRINT":
                    said = ("Board A may be stretched by the printer. Measure it: it should be "
                            f"{board_cm[0]:.1f} by {board_cm[1]:.1f} centimetres. Print it again if not.")
                voice.say(said + (f" Next: {spoken(nxt)}." if nxt else ""), force=True)
            finally:
                mirrored[name] = win.mirror
                cam.stop()
        lines = [f"{n}: {results.get(n, 'not done')}" + ("  (AUTOFOCUS STUCK ON)" if n in autofocus_on else "")
                 for n in (names[s] for s in slots)]
        all_good = all(results.get(names[s], "").startswith("FIT GOOD") for s in slots)
        voice.say("All cameras done." if all_good else "Lens calibration finished. Some cameras need another try.",
                  force=True)
        disp = np.zeros((size[1], size[0], 3), np.uint8)
        for j, line in enumerate(lines):
            big_text(disp, line, int(disp.shape[0] * 0.25) + 60 * j, 1.3, GREEN if "FIT GOOD" in line else YELLOW)
        disp = overlay(disp, "Lens calibration", "", "ALL FIT GOOD" if all_good else
                       "CHECK YOUR PRINT" if any(r == "CHECK YOUR PRINT" for r in results.values()) else
                       "Some need REDO", "",
                       GREEN if all_good else YELLOW, "any key to close")
        win.show(disp)
        while cv2.waitKey(50) == -1:  # any key closes; the last prompt still gets spoken meanwhile
            voice.tick()
    finally:
        cv2.destroyAllWindows()
        voice.close()
    for line in lines:
        log.info(line)
    log.info("Log: %s", log_file)
    return 0  # GOOD or REDO, the result was shown and spoken; only a crash is an error


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
