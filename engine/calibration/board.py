"""ChArUco boards from settings/cameras.yaml, and a tiny PDF writer so they print at exact size.

calibration.boards.small is the lens-calibration board (one sheet of paper, held close to each
camera). More boards can be added under calibration.boards; give each its own marker ids
(first_marker_id) so they can never be mixed up.
"""

import zlib

import cv2
import numpy as np

MM_PER_INCH = 25.4


def make_board(bcfg):
    """CharucoBoard from a calibration.boards.<name> config dict (lengths in mm, board units in metres)."""
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, bcfg["dictionary"]))
    sx, sy = bcfg["squares"]
    n_markers = (sx * sy) // 2
    ids = np.arange(int(bcfg["first_marker_id"]), int(bcfg["first_marker_id"]) + n_markers, dtype=np.int32)
    return cv2.aruco.CharucoBoard((sx, sy), bcfg["square_mm"] / 1000.0, bcfg["marker_mm"] / 1000.0, d, ids)


def board_image(bcfg, dpi):
    sx, sy = bcfg["squares"]
    px_per_mm = dpi / MM_PER_INCH
    size = (int(round(sx * bcfg["square_mm"] * px_per_mm)), int(round(sy * bcfg["square_mm"] * px_per_mm)))
    return make_board(bcfg).generateImage(size, marginSize=0, borderBits=1)


def write_pdf(path, gray, page_mm, image_mm, offset_mm, captions=(), rulers_mm=(), boxes_mm=(), arrows_mm=()):
    """One-page PDF with a grayscale image placed at an exact physical size.

    page_mm, image_mm, offset_mm: (w, h) in millimetres, offset from the page's bottom-left.
    captions: list of (x_mm, y_mm, size_pt, text). rulers_mm: list of (x_mm, y_mm, length_mm).
    boxes_mm: dashed rectangles (x_mm, y_mm, w_mm, h_mm). arrows_mm: (x0_mm, y0_mm, x1_mm, y1_mm), head at the end.
    """
    pt = 72.0 / MM_PER_INCH
    h, w = gray.shape
    img = zlib.compress(np.ascontiguousarray(gray, np.uint8).tobytes(), 9)
    ops = [f"q {image_mm[0] * pt:.3f} 0 0 {image_mm[1] * pt:.3f} {offset_mm[0] * pt:.3f} {offset_mm[1] * pt:.3f} cm /Im0 Do Q"]
    for x, y, length in rulers_mm:
        ops.append(f"0.5 w {x * pt:.3f} {y * pt:.3f} m {(x + length) * pt:.3f} {y * pt:.3f} l S")
        for t in (x, x + length):
            ops.append(f"{t * pt:.3f} {(y - 2) * pt:.3f} m {t * pt:.3f} {(y + 2) * pt:.3f} l S")
    for x, y, bw, bh in boxes_mm:
        ops.append(f"q 0.8 w [4 3] 0 d {x * pt:.3f} {y * pt:.3f} {bw * pt:.3f} {bh * pt:.3f} re S Q")
    for x0, y0, x1, y1 in arrows_mm:
        d = np.array([x1 - x0, y1 - y0], float)
        d /= max(np.linalg.norm(d), 1e-9)
        n = np.array([-d[1], d[0]])
        tip = np.array([x1, y1])
        a, b = tip - 4 * d + 2 * n, tip - 4 * d - 2 * n
        ops.append(f"q 1.2 w {x0 * pt:.3f} {y0 * pt:.3f} m {(x1 - 3 * d[0]) * pt:.3f} {(y1 - 3 * d[1]) * pt:.3f} l S "
                   f"{tip[0] * pt:.3f} {tip[1] * pt:.3f} m {a[0] * pt:.3f} {a[1] * pt:.3f} l {b[0] * pt:.3f} {b[1] * pt:.3f} l "
                   "h f Q")
    for x, y, size, text in captions:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 {size} Tf {x * pt:.3f} {y * pt:.3f} Td ({safe}) Tj ET")
    content = "\n".join(ops).encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_mm[0] * pt:.3f} {page_mm[1] * pt:.3f}] "
         f"/Resources << /XObject << /Im0 4 0 R >> /Font << /F1 6 0 R >> >> /Contents 5 0 R >>").encode("ascii"),
        (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray "
         f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(img)} >>\nstream\n").encode("ascii") + img + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii")
    out += b"".join(f"{o:010d} 00000 n \n".encode("ascii") for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    with open(path, "wb") as f:
        f.write(out)
