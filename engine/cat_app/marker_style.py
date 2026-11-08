"""How the cat's markers in VR look: colour, shade, size and opacity.

Shared by the app (for the previews) and the tracker bridge (for the real overlays), so what you see in
the app is what you get in VR. Needs only numpy. Images are RGBA uint8 arrays (height, width, 4).

Recolouring only touches the marker's main colour (the orange fur, the ring), found as the most common
strongly coloured hue in the picture. Eyes, whiskers, the nose and white parts keep their colours, and
the light and dark parts of the fur keep their light and dark, so the icon still reads as a cat.
"""

import copy
import json
from pathlib import Path


class _LazyNumpy:
    """numpy (about 18 MB) is only loaded the first time an icon is actually recoloured, so the app doesn't
    carry it unless you open Marker look. The tracker has it loaded anyway."""

    def __getattr__(self, name):
        import numpy
        globals()["np"] = numpy
        return getattr(numpy, name)


np = _LazyNumpy()

# Which overlay pictures each style group changes. "warning" is the red icon shown when the cat is
# close, so by default it keeps its red: that is what makes it stand out.
GROUPS = {
    "cat": {"label": "Cat icon", "files": ("cat.png", "cat_rest.png", "cat_move.png")},
    "warning": {"label": "Warning icon (cat close)", "files": ("cat_close.png",)},
    "ring": {"label": "Floor ring", "files": ("ring.png",)},
    "arrow": {"label": "Edge arrow", "files": ("edge_arrow.png",)},
}

DEFAULTS = {
    "cat": {"colour": None, "shade": 0.0, "size": 1.0, "opacity": 1.0},
    "warning": {"colour": None, "shade": 0.0, "size": 1.0, "opacity": 1.0},
    "ring": {"colour": None, "shade": 0.0, "size": 1.0, "opacity": 1.0},
    "arrow": {"colour": None, "shade": 0.0, "size": 1.0, "opacity": 1.0},
}

# Limits. The cat and warning icons can't fade below 25% or shrink below half size, so the marker
# can't be made invisible by accident, nor can the edge arrow that points to the cat
# when it's close; the ring can be switched off entirely.
LIMITS = {
    "shade": (-0.8, 0.8),
    "size": (0.5, 2.5),
    "opacity": {"cat": (0.25, 1.0), "warning": (0.4, 1.0), "ring": (0.0, 1.0), "arrow": (0.4, 1.0)},
}

PALETTE = ["#f0973c", "#e8483c", "#f2c94c", "#7bd35a", "#2fbf9b", "#38b6e8",
           "#4a7cf0", "#9b6cf0", "#e86cc8", "#ffffff", "#9aa3ad", "#3a3f47"]


def group_for(filename):
    name = Path(str(filename)).name.lower()
    for g, info in GROUPS.items():
        if name in info["files"]:
            return g
    return None


def clamp_style(style):
    """A full, valid style dict from whatever was saved (missing or bad values fall back to defaults)."""
    out = copy.deepcopy(DEFAULTS)
    for g in out:
        s = (style or {}).get(g) or {}
        c = s.get("colour")
        if isinstance(c, str) and len(c) == 7 and c.startswith("#"):
            try:
                int(c[1:], 16)
                out[g]["colour"] = c.lower()
            except ValueError:
                pass
        for k in ("shade", "size"):
            try:
                lo, hi = LIMITS[k]
                out[g][k] = float(min(hi, max(lo, float(s.get(k, out[g][k])))))
            except (TypeError, ValueError):
                pass
        try:
            lo, hi = LIMITS["opacity"][g]
            out[g]["opacity"] = float(min(hi, max(lo, float(s.get("opacity", out[g]["opacity"])))))
        except (TypeError, ValueError):
            pass
    return out


def load(path):
    try:
        return clamp_style(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clamp_style({})


def save(path, style):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clamp_style(style), indent=2), encoding="utf-8")
    tmp.replace(path)


def key(group_style):
    """A short text that changes whenever the picture would change (for cache file names)."""
    return "%s_%+.2f" % ((group_style.get("colour") or "orig").lstrip("#"), group_style.get("shade", 0.0))


# ---- colour maths ----------------------------------------------------------------------------------

def _rgb_to_hsv(rgb):
    rgb = rgb.astype(np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    h = h / 6.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def _hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    choices = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    r = np.choose(i, [c[0] for c in choices])
    g = np.choose(i, [c[1] for c in choices])
    b = np.choose(i, [c[2] for c in choices])
    return np.clip(np.stack([r, g, b], -1) * 255 + 0.5, 0, 255).astype(np.uint8)


def _hex_to_hsv(colour):
    c = np.array([[[int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)]]], np.uint8)
    h, s, v = _rgb_to_hsv(c)
    return float(h[0, 0]), float(s[0, 0]), float(v[0, 0])


def main_colour_mask(rgba):
    """Pixels of the picture's main colour: visible, clearly coloured, and near the most common hue."""
    h, s, v = _rgb_to_hsv(rgba[..., :3])
    visible = rgba[..., 3] > 8
    coloured = visible & (s > 0.08) & (v > 0.15)
    if coloured.sum() < 10:
        return np.zeros(h.shape, bool), h, s, v
    hist, edges = np.histogram(h[coloured & (s > 0.3)] if (coloured & (s > 0.3)).sum() > 10 else h[coloured],
                               bins=36, range=(0, 1))
    centre = (edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2
    dh = np.abs(((h - centre) + 0.5) % 1.0 - 0.5)
    return coloured & (dh < 0.07), h, s, v


def restyle(rgba, group_style):
    """The picture recoloured and shaded as group_style says (size and opacity are applied by the
    overlay itself, not baked into the picture). Returns a new RGBA array."""
    colour = group_style.get("colour")
    shade = float(group_style.get("shade", 0.0))
    if not colour and abs(shade) < 1e-3:
        return rgba.copy()
    out = rgba.copy()
    mask, h, s, v = main_colour_mask(rgba)
    if not mask.any():
        return out
    if colour:
        th, ts, tv = _hex_to_hsv(colour)
        # keep each pixel's saturation and brightness relative to the main colour, so a pale fill stays
        # pale and a darker edge stays darker, just in the new colour
        s_ref, v_ref = float(np.median(s[mask])), float(np.median(v[mask]))
        nh = np.full(h.shape, th, np.float32)
        ns = np.clip(s * (ts / max(s_ref, 1e-3)), 0, 1)
        nv = np.clip(v * (tv / max(v_ref, 1e-3)), 0, 1)
        rgb = _hsv_to_rgb(nh, ns, nv)
    else:
        rgb = rgba[..., :3].copy()
    rgb = rgb.astype(np.float32)
    if shade > 0:  # lighter: toward white
        rgb = rgb + (255 - rgb) * shade
    elif shade < 0:  # darker: toward black
        rgb = rgb * (1 + shade)
    out[..., :3][mask] = np.clip(rgb[mask] + 0.5, 0, 255).astype(np.uint8)
    return out
