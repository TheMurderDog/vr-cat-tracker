"""Test mode for lining up the avatar's snake: a pretend cat held still on the floor straight ahead of
where you stand, sent to VRChat with every parameter exactly as the tracker sends them, and shown
with the same SteamVR ring and icon. No cameras or GPU needed; it uses the saved anchor.

The spot is fixed in the room once placed, so you can walk around it and check that the snake stays
on the ring. In this window:  1 = place it 1 m ahead of you now,  2 = 2 m ahead,  q = quit.
Its heading points the way you faced when it was placed (CatRoomYaw = your HeadRoomYaw then).

    osc_test.bat          (or osc_test.bat --distance 2)
"""

import argparse
import math
import time

import numpy as np

from cat_tracker import anchor as anc
from cat_tracker import settings
from cat_tracker.osc import OscCat, OscStream, room_head
from cat_tracker.vrlink import VRLink, billboard, flat
from core.config import resolve_path
from core.runlog import start_run

try:
    import msvcrt  # Windows: read keys from this window without waiting
except ImportError:  # elsewhere (tests): no keys, it just holds the first spot
    msvcrt = None


def spot_ahead(vr, raw_to_cam, distance):
    """(x, z, yaw) in the room frame, distance metres ahead of the headset along its heading, or None."""
    hmd = vr.headset()
    if hmd is None:
        return None
    head = room_head(raw_to_cam @ hmd)
    if head is None:
        return None
    x, z, yaw = head
    y = math.radians(yaw)
    return x + distance * math.sin(y), z - distance * math.cos(y), yaw


def main():
    ap = argparse.ArgumentParser(description="Hold a pretend cat ahead of you for lining up the avatar")
    ap.add_argument("--distance", type=float, default=1.0, help="metres ahead when it starts (1 or 2 keys change it)")
    ap.add_argument("--config", help="camera core config.yaml (default: its own)")
    ap.add_argument("--cat-config", help="cat tracker config.yaml (default: cat_tracker/config.yaml)")
    args = ap.parse_args()
    cfg = settings.load(args.config, args.cat_config)
    cc = cfg["cat"]
    oc = cc.get("overlay", {}) or {}
    log, _ = start_run("cat_osc_test", cfg)
    raw_to_cam = anc.load(cfg)
    if raw_to_cam is None:
        log.error("No saved anchor yet: run run.bat once (with the walk-around) first")
        return 1
    cam_to_raw = np.linalg.inv(raw_to_cam)
    floor_y = float((cc.get("locate", {}) or {}).get("floor_y_m", 0.0))
    try:
        vr = VRLink()
    except Exception as e:  # noqa: BLE001
        log.error("SteamVR not available (%s). Start SteamVR first", e)
        return 1
    vr.add_overlay("icon", resolve_path(oc["icon"]), oc.get("icon_width_m", 0.28))
    vr.add_overlay("ring", resolve_path(oc["ring"]), oc.get("ring_width_m", 0.55))
    osc = OscCat(cc.get("vrchat", {}) or {})
    hz = float((cc.get("vrchat", {}) or {}).get("send_hz", 60))
    stream = OscStream(osc, vr, hz, log)
    log.info("Test cat: sending to VRChat at %s:%d, %g a second. Keys: 1 = 1 m ahead, 2 = 2 m ahead, q = quit",
             *osc.addr, hz)

    spot, want = None, args.distance
    try:
        while True:
            if want is not None:
                s = spot_ahead(vr, raw_to_cam, want)
                if s is not None:  # the headset may not be tracking yet: try again next time
                    spot = s
                    log.info("Test cat %.0f m ahead: room x %.2f z %.2f, heading %.0f deg", want, *spot)
                    want = None
            if msvcrt is not None and msvcrt.kbhit():
                k = msvcrt.getwch().lower()
                if k in "12":
                    want = float(k)
                elif k == "q":
                    break
            if vr.quit_requested():
                break
            if spot is not None:
                x, z, yaw = spot
                cat_cam = np.array([x, floor_y + 0.15, z])  # its middle, as the tracker reports it
                stream.set_cat(cat_cam, True, "normal", False, raw_to_cam, yaw)
                M = vr.raw_to_standing()
                to_standing = M @ cam_to_raw
                p = to_standing[:3, :3] @ cat_cam + to_standing[:3, 3]
                ring = to_standing[:3, :3] @ np.array([x, floor_y + 0.01, z]) + to_standing[:3, 3]
                hmd = vr.headset()
                hmd_st = (M @ hmd)[:3, 3] if hmd is not None else p + np.array([0, 0, 1.0])
                vr.place("icon", billboard(p + np.array([0, float(oc.get("icon_lift_m", 0.3)), 0]), hmd_st), 1.0)
                vr.place("ring", flat(ring), 1.0)
            time.sleep(1 / 30)
    finally:
        stream.stop()
        osc.close()
        vr.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
