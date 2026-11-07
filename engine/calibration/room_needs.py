"""After a room solve: which cameras are GOOD, and what the others need, in plain words.

Pure logic (no cameras or SteamVR), so it can be tested. try_solve() never raises: a camera that can't be placed at
all is reported as needing more stops, and the rest are still solved (without it) so they can be marked done.
"""

import numpy as np

from calibration import room
from capture.camera import spoken

MIN_STOPS = 6       # the solver needs at least this many per camera
MIN_GOOD_STOPS = 12  # a low error from fewer stops than this isn't trusted across the room
ENOUGH_STOPS = 15   # under this a camera that isn't GOOD is asked for more
MIN_CELLS = 6       # of the 3 x 3 parts of its picture the marker should have been seen in
MIN_DEPTH_M = 0.8   # range of distances from the camera
MIN_HEIGHT_M = 0.8  # range of heights
MIN_TILT_DEG = 15   # tilt variety, seen from that camera
BAD_SHARE = 0.25    # share of a camera's stops the solver threw out as not fitting


def tilt_spread(rot):
    """Smallest spread (degrees) of any tracker axis over these rotations: low = the card barely tilted."""
    rot = np.asarray(rot, float)
    if len(rot) < 2:
        return 0.0
    out = []
    for k in range(3):
        a = rot[:, :, k]
        m = a.mean(axis=0)
        m = m / max(np.linalg.norm(m), 1e-9)
        out.append(float(np.degrees(np.max(np.arccos(np.clip(a @ m, -1, 1))))))
    return min(out)


def camera_stats(obs, slot, size, centre=None):
    """Counts and spreads for one camera's stops. centre: its position (metres) if known."""
    sel = [o for o in obs if o[0] == slot]
    st = {"stops": len(sel)}
    if not sel:
        return dict(st, cells=0, depth_m=0.0, height_m=0.0, tilt_deg=0.0)
    px = np.array([o[1] for o in sel], float)
    pos = np.array([o[2] for o in sel], float)
    w, h = size
    cells = {(min(2, max(0, int(3 * x / w))), min(2, max(0, int(3 * y / h)))) for x, y in px}
    st["cells"] = len(cells)
    st["height_m"] = float(np.ptp(pos[:, 1]))
    st["depth_m"] = float(np.ptp(np.linalg.norm(pos - np.asarray(centre, float), axis=1))) if centre is not None else None
    st["tilt_deg"] = tilt_spread([o[3] for o in sel])
    return st


def needs_for(name, st, cam=None, max_rms=3.0):
    """[] if GOOD, else plain sentences saying what the camera needs, most useful first."""
    if cam is not None and cam["rms_px"] <= max_rms and st["stops"] >= MIN_GOOD_STOPS:
        return []
    out = []
    if st["stops"] < ENOUGH_STOPS or cam is None:
        out.append(f"{spoken(name, True)} needs more stops.")
    if st["cells"] < MIN_CELLS:
        out.append(f"Move Board B near the edges of what {spoken(name)} sees.")
    if st["depth_m"] is not None and st["depth_m"] < MIN_DEPTH_M:
        out.append(f"{spoken(name, True)} needs Board B closer to it, and farther away.")
    if st["height_m"] < MIN_HEIGHT_M:
        out.append(f"Hold Board B low and high in front of {spoken(name)}.")
    if st["tilt_deg"] < MIN_TILT_DEG:
        out.append(f"Tilt Board B toward {spoken(name)}, and away from it.")
    if cam is not None and st["stops"] and cam.get("dropped", 0) / (st["stops"]) > BAD_SHARE:
        out.append(f"Some of {spoken(name)}'s stops didn't fit. Hold Board B still at each stop.")
    if not out:
        out.append(f"{spoken(name, True)} needs more stops, spread around the room.")
    return out


def _placeable(obs, intrinsics, slot):
    from calibration import intrinsics as intr
    sel = [o for o in obs if o[0] == slot]
    if len(sel) < MIN_STOPS:
        return False
    try:
        room.initial_pose(np.array([o[2] for o in sel]), intr.undistort_points(np.array([o[1] for o in sel]),
                                                                                intrinsics[slot]))
        return True
    except Exception:  # noqa: BLE001
        return False


def try_solve(obs, intrinsics, names, size, max_rms=3.0, log=None, start=None):
    """Solve what can be solved. Returns (out or None if not every camera could be placed, needs) where needs is
    {slot: [sentences]} with [] for a GOOD camera. out has the room.solve format when every camera was placed."""
    n = len(names)
    ok = [s for s in range(n) if _placeable(obs, intrinsics, s)]
    out_sub = None
    if ok:
        remap = {s: i for i, s in enumerate(ok)}
        sub = [(remap[o[0]], o[1], o[2], o[3]) for o in obs if o[0] in remap]
        try:
            out_sub = room.solve(sub, [intrinsics[s] for s in ok], len(ok), log=log if len(ok) == n else None,
                                 names=[names[s] for s in ok], start=start if len(ok) == n else None)
        except Exception as e:  # noqa: BLE001
            if log:
                log.warning("Solve failed: %s", e)
            out_sub, ok = None, []
    needs = {}
    cams = {s: out_sub["cameras"][i] for i, s in enumerate(ok)} if out_sub else {}
    for s in range(n):
        cam = cams.get(s)
        st = camera_stats(obs, s, size, cam["position_m"] if cam else None)
        needs[s] = needs_for(names[s], st, cam, max_rms)
        if log:
            log.info("  %-6s %s: %s", names[s], "FIT GOOD" if not needs[s] else "needs", needs[s] or
                     f"{cam['rms_px']:.2f} px")
    return (out_sub if len(ok) == n else None), needs


def sharpness(frame):
    """How crisp a camera's picture is (variance of the Laplacian). It depends on what the camera looks at too, so
    it's only compared between cameras as a hint, never as a verdict."""
    import cv2
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def verdicts(out, obs, lenses, names, size, max_rms=3.0, ok_px=4.5, frames=None, lens_max_rms=0.8):
    """Per camera at the end: (GOOD / OK / NOT GOOD, rms, advice or None). OK is a little less precise but fine to
    use. The advice says what to check when more stops couldn't help, from what the data can actually show:
    many stops thrown out (the card's device wobbles), a lens result that is itself poor (redo the lens step), or a
    picture much softer than the other cameras' (clean the lens, check focus and mounting)."""
    sharp = {}
    if frames:
        sharp = {s: sharpness(f) for s, f in frames.items() if f is not None}
    res = []
    for s, (name, cam) in enumerate(zip(names, out["cameras"])):
        rms = float(cam["rms_px"])
        label = "GOOD" if rms <= max_rms else "OK" if rms <= ok_px else "NOT GOOD"
        advice = None
        if label != "GOOD":
            others = [v for k, v in sharp.items() if k != s]
            if cam.get("dropped", 0) > 0.2 * max(cam.get("observations", 1), 1):
                advice = f"Many of {spoken(name)}'s stops didn't fit: make sure the device on Board B can't wobble."
            elif float(lenses[s].get("rms_px", 0)) > lens_max_rms or lenses[s].get("status", "GOOD") != "GOOD":
                advice = f"{spoken(name, True)}'s lens calibration doesn't fit well: redo the lens step for {spoken(name)}, then room calibration."
            elif s in sharp and others and sharp[s] < 0.7 * float(np.median(others)):
                advice = (f"{spoken(name, True)}'s picture is softer than the other cameras': wipe its lens, and check it's in focus "
                          "and firmly mounted. If you change its focus, redo its lens step and the room walk.")
            else:
                advice = (f"{spoken(name, True)} sees Board B less precisely than the others: check it's firmly mounted and its "
                          "lens is clean." + (" It works as it is." if label == "OK" else ""))
        res.append((label, rms, advice))
    return res
