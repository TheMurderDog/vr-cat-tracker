"""Write the calibration boards as print-ready PDFs (and PNGs) to calibration/boards/.

Run from the repo root:  python -m tools.make_boards
Print each PDF at 100% / "Actual size" (never "Fit to page"), then measure the printed
100 mm ruler line and one square. If the square is not exactly the size in config.yaml,
put the measured value in calibration.boards.<name>.square_mm (and marker_mm scaled the same).
Glue the board flat onto something rigid; a bent board ruins calibration.
"""

import argparse

import cv2

from calibration.board import board_image, write_pdf
from core.config import get, load_config, resolve_path
from core.runlog import start_run


def main():
    ap = argparse.ArgumentParser(description="Write printable ChArUco boards")
    ap.add_argument("--config")
    args = ap.parse_args()
    cfg = load_config(args.config)
    log, log_file = start_run("make_boards", cfg)
    out_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data")) / "boards"
    out_dir.mkdir(parents=True, exist_ok=True)
    dpi = int(get(cfg, "calibration.print_dpi", 300))
    for name, b in get(cfg, "calibration.boards", {}).items():
        img = board_image(b, dpi)
        sx, sy = b["squares"]
        board_mm = (sx * b["square_mm"], sy * b["square_mm"])
        page_mm = tuple(b["page_mm"])
        free_y = page_mm[1] - board_mm[1]
        off = ((page_mm[0] - board_mm[0]) / 2, free_y * 0.6)  # extra room below for the caption and ruler
        if off[0] < 8 or free_y * 0.4 < 8 or off[1] < 22:
            log.warning("%s board (%.0f x %.0f mm) barely fits its page (%.0f x %.0f mm)", name, *board_mm, *page_mm)
        caption = (f"Calibration {name} board: {sx}x{sy} squares of {b['square_mm']:g} mm, markers {b['marker_mm']:g} mm, "
                   f"{b['dictionary']} from id {b['first_marker_id']}. Print at 100%.")
        pdf = out_dir / f"board_{name}.pdf"
        write_pdf(pdf, img, page_mm, board_mm, off,
                  captions=[(off[0], off[1] - 6, 7, caption), (off[0], off[1] - 14, 7, "This line must measure 100 mm:")],
                  rulers_mm=[(off[0] + 45, off[1] - 13.2, 100)])
        cv2.imwrite(str(out_dir / f"board_{name}.png"), img)
        log.info("%s: %s (%.0f x %.0f mm board on a %.0f x %.0f mm page)", name, pdf, *board_mm, *page_mm)
    rc = get(cfg, "calibration.room", {})
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, rc["marker_dictionary"]))
    mm = float(rc["marker_mm"])
    img = cv2.aruco.generateImageMarker(d, int(rc["marker_id"]), int(round(mm * dpi / 25.4)), borderBits=1)
    page = (215.9, 279.4)
    off = ((page[0] - mm) / 2, (page[1] - mm) / 2 + 15)
    pdf = out_dir / "tracker_marker.pdf"
    write_pdf(pdf, img, page, (mm, mm), off,
              captions=[(off[0], off[1] - 8, 8, f"Tracker marker: {rc['marker_dictionary']} id {rc['marker_id']}, "
                                               f"{mm:g} mm. Print at 100%. Keep the white border."),
                        (off[0], off[1] - 16, 8, "Glue to stiff card. Fix the tracker rigidly above the top edge, dome clear."),
                        (off[0], off[1] - 26, 7, "This line must measure 100 mm:")],
              rulers_mm=[(off[0] + 45, off[1] - 25.2, 100)])
    log.info("tracker marker: %s", pdf)
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
