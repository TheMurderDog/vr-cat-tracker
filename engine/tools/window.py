"""The big windows of the setup screen and the calibration wizards: a normal window that opens maximised on the main
monitor (so it can be moved and resized), with every picture fitted and centred to the window's real size, on
whichever monitor it is. f switches true fullscreen on and off.

Sizing pictures to the window itself, not to "the screen", is what keeps them centred with several monitors of
different sizes (fullscreen goes to the monitor the window is on).
"""

import cv2
import numpy as np


def maximise(title):
    """Put the window on the main monitor and maximise it (Windows; elsewhere it just stays a normal window)."""
    try:
        cv2.moveWindow(title, 40, 40)  # the main monitor's top left: maximising then fills that monitor
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, title)
        if hwnd:
            u.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    except Exception:  # noqa: BLE001  (not Windows, or no such window yet)
        pass


def open_window(title, size=(1600, 900)):
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, *size)
    cv2.imshow(title, np.zeros((size[1], size[0], 3), np.uint8))
    cv2.waitKey(1)
    maximise(title)


def window_size(title, default=None):
    """The inside of the window in pixels (w, h), as it is right now, or default."""
    try:
        x, y, w, h = cv2.getWindowImageRect(title)
        if w >= 200 and h >= 150:
            return int(w), int(h)
    except cv2.error:
        pass
    return default


def fit_into(img, size):
    """img scaled to fit size (w, h) and centred on black, at exactly that size."""
    w, h = size
    s = min(w / img.shape[1], h / img.shape[0])
    nw, nh = max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))
    out = np.zeros((h, w, 3), np.uint8)
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    x, y = (w - nw) // 2, (h - nh) // 2
    out[y:y + nh, x:x + nw] = small if small.ndim == 3 else cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
    return out, s, (x, y)


def closed(title):
    """Was the window closed with its X? (Also True when it doesn't exist.)"""
    try:
        return cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def quit_when_closed(title, key=ord("q")):
    """Closing the window with its X quits the tool, exactly as its quit key does: once the window has been shown
    and is then closed, every cv2.waitKey / waitKeyEx in this process returns the quit key, and the window is never
    drawn again (cv2.imshow would open it once more). So each tool's own quit path runs as usual: what it saves on
    quit is saved, cameras are released, and it ends, closing its launcher too."""
    import logging
    wait, wait_ex, show = cv2.waitKey, cv2.waitKeyEx, cv2.imshow
    state = {"shown": False, "closed": False}

    def imshow(name, img):
        if name == title:
            if state["closed"]:
                return
            state["shown"] = True
        show(name, img)

    def check(k):
        if state["shown"] and not state["closed"] and closed(title):
            state["closed"] = True
            logging.getLogger("window").info("The window was closed: quitting, as with the quit key")
        return key if state["closed"] else k

    cv2.waitKey = lambda delay=0: check(wait(delay))
    cv2.waitKeyEx = lambda delay=0: check(wait_ex(delay))
    cv2.imshow = imshow
    return state


def set_fullscreen(title, on):
    cv2.setWindowProperty(title, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if on else cv2.WINDOW_NORMAL)
    if not on:
        maximise(title)
