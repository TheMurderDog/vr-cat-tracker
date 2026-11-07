"""Write the calibration boards as print-ready PDFs (and PNGs) to my_data/calibration/boards/.

Only for custom sizes (docs/technical/custom_boards.md); no launcher. Run from engine/:  python -m tools.make_boards
Print each PDF at 100% / "Actual size", then measure the checkerboard's width and height. Shrunk evenly is
harmless (the lens result doesn't depend on the board's overall size), but a printer that stretches one way only
spoils the lens calibration: if the width is right and the height isn't (or the other way round), print again.
The room marker's size never matters (only its centre is used). Glue the board flat onto something rigid; a bent
board ruins calibration.
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
    out_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration")) / "boards"
    out_dir.mkdir(parents=True, exist_ok=True)
    dpi = int(get(cfg, "calibration.print_dpi", 300))
    for name, b in get(cfg, "calibration.boards", {}).items():
        img = board_image(b, dpi)
        sx, sy = b["squares"]
        board_mm = (sx * b["square_mm"], sy * b["square_mm"])
        page_mm = tuple(b["page_mm"])
        free_y = page_mm[1] - board_mm[1]
        off = ((page_mm[0] - board_mm[0]) / 2, free_y * 0.6)  # extra room below for the captions
        if off[0] < 8 or free_y * 0.4 < 8 or off[1] < 22:
            log.warning("%s board (%.0f x %.0f mm) barely fits its page (%.0f x %.0f mm)", name, *board_mm, *page_mm)
        title = "BOARD A" if name == "small" else f"BOARD {name.upper()}"  # what the guides and the voice call it
        sub = "the checkerboard, for lens calibration (step 2)" if name == "small" else "a custom board"
        caption = (f"Calibration {name} board: {sx}x{sy} squares of {b['square_mm']:g} mm, markers {b['marker_mm']:g} mm, "
                   f"{b['dictionary']} from id {b['first_marker_id']}. Print at 100%.")
        measure = (f"Measure the checkerboard: {board_mm[0] / 10:.1f} cm wide, {board_mm[1] / 10:.1f} cm tall. "
                   "If only one of them is off, the printer stretched it: print it again.")
        pdf = out_dir / f"board_{name}.pdf"
        write_pdf(pdf, img, page_mm, board_mm, off,
                  captions=[(off[0], off[1] + board_mm[1] + 4, 16, title),  # just above the board: US Letter has little room
                            (off[0] + 32, off[1] + board_mm[1] + 4, 8, sub),
                            (off[0], off[1] - 6, 7, caption), (off[0], off[1] - 14, 8, measure)])
        cv2.imwrite(str(out_dir / f"board_{name}.png"), img)
        log.info("%s: %s (%.0f x %.0f mm board on a %.0f x %.0f mm page)", name, pdf, *board_mm, *page_mm)
    rc = get(cfg, "calibration.room", {})
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, rc["marker_dictionary"]))
    mm = float(rc["marker_mm"])
    img = cv2.aruco.generateImageMarker(d, int(rc["marker_id"]), int(round(mm * dpi / 25.4)), borderBits=1)
    # the marker goes on the same paper as the lens board (US letter by default; A4 if page_mm says so)
    page = tuple(get(cfg, "calibration.boards.small.page_mm", [215.9, 279.4]))
    off = ((page[0] - mm) / 2, (page[1] - mm) / 2 + 15)
    pdf = out_dir / "tracker_marker.pdf"
    # the mounting area: the space above the marker, where the tracker or controller goes on the back of the card,
    # its top sticking up past the top edge (a zone and an arrow, as controllers come in every shape)
    top = off[1] + mm
    zone = (page[0] / 2 - 60, top + 4, 120, page[1] - top - 12)
    cx = page[0] / 2

    lines = ["ON THE BACK: a tracker or controller goes here",
             "Tape or rubber-band it on, its top sticking up past the top edge.",
             "It just mustn't wobble, and mustn't cover the marker."]
    write_pdf(pdf, img, page, (mm, mm), off,
              captions=[(off[0], 12, 22, "BOARD B"), (off[0] + 42, 12, 9, "the marker card, for room calibration (step 2) "
                                                                             "and checking focus (step 1)"),
                        (off[0], off[1] - 8, 8, f"Tracker marker: {rc['marker_dictionary']} id {rc['marker_id']}, "
                                               f"{mm:g} mm. Any print size works. Keep the white border."),
                        (off[0], off[1] - 16, 8, "Glue this sheet to stiff card. Mount the tracker or controller "
                                                 "in the dashed area, on the back.")] +
                       [(zone[0] + 7, zone[1] + zone[3] - 10 - 6.5 * i, 10 if i == 0 else 8, t) for i, t in enumerate(lines)],
              boxes_mm=[zone], arrows_mm=[(cx + 50, zone[1] + 4, cx + 50, page[1] - 7)])  # printers can't reach the edge
    log.info("tracker marker: %s", pdf)
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
