# Custom board or marker sizes

The sheets in `0_start_here/print_these` (US Letter and A4) match the default settings, and almost everyone should
use them. Make your own only if you need a different size: a bigger Board A (the lens checkerboard) for cameras far away, a bigger room
marker for a large room, or other paper.

## 1. Change the settings

In `settings/cameras.yaml`, under `calibration`:

- `boards.small`: Board A, the lens checkerboard. `squares` (columns, rows), `square_mm`, `marker_mm` (the ArUco inside each
  square, about 0.75 of `square_mm`), `dictionary`, `first_marker_id`, and `page_mm` (`[215.9, 279.4]` US Letter,
  `[210.0, 297.0]` A4). The board must fit the page with room for its caption.
- `room`: Board B, the room marker card. `marker_dictionary`, `marker_id`, `marker_mm`. It's printed on the same paper size as
  the board.

The lens wizard and the room calibration read these same settings, so the sheet you print and the settings always
have to match. Only `square_mm` and `marker_mm` change the results; the others decide which markers are looked for.

## 2. Make the sheets

From the top folder, in a terminal:

```
cd engine
..\.venv\Scripts\python.exe -m tools.make_boards
```

It writes `board_small.pdf` (and `.png`) and `tracker_marker.pdf` to `my_data/calibration/boards/`.

## 3. Print and measure

Print **at 100% / "Actual size"**. Measure Board A's width and height (the caption under it says what
they should be). If only one is off, the printer stretched it: print it again. No setting needs correcting after
printing.

Only one thing about the print matters: the board must not be stretched one way more than the other. Its
overall size doesn't matter (a lens calibration comes out the same from a board printed a few percent small, so
"Fit to page" is harmless), and neither does Board B's size (only its centre is used). But a printer that
stretches the paper one way by even 1% makes the lens model several pixels wrong across the picture, and the
wizard can't tell, because the board then fits its own wrong shape. Measured in simulation through a real lens:
3% or 6% smaller changed nothing; a 1% one-way stretch gave about 12 px of error at the edges of the picture,
3% about 40 px.
