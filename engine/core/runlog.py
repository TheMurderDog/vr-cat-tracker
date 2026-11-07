"""Per-run logging: every script logs to its own timestamped file under my_data/logs as well as the console."""

import datetime as _dt
import json
import logging
import platform
import os
import sys
import threading

from .config import get, resolve_path

_FMT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(threadName)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


TEST_ENV = "CAT_TRACKER_TEST"  # set (to anything) by automated tests


def is_test_run(argv=None):
    """An automated test, not a person using the tool: CAT_TRACKER_TEST is set, or the script is a test or probe
    (test_*.py, probe_*.py). How the program was started is not a hint: SteamVR's own start looks unusual too."""
    argv = sys.argv if argv is None else argv
    if os.environ.get(TEST_ENV):
        return True
    first = os.path.basename(argv[0]) if argv and argv[0] else ""
    return first.lower().startswith(("test_", "probe_"))


def start_run(name, cfg):
    """Configure logging for this process and return (logger, log_file_path).

    Writes a header with the command line, Python, OS and the full config so a log
    file alone is enough to diagnose a run.
    """
    log_dir = resolve_path(get(cfg, "logging.dir", "my_data/logs/cameras"))
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    test = is_test_run()
    log_file = log_dir / f"{stamp}_{name}{'_TEST' if test else ''}.log"  # tests never look like a person's run

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(get(cfg, "logging.file_level", "DEBUG"))
    fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(get(cfg, "logging.console_level", "INFO"))
    ch.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ch)

    _install_excepthooks()
    _prune(log_dir, get(cfg, "logging.keep_last", 100))

    log = logging.getLogger(name)
    if test:
        log.warning("AUTOMATED TEST RUN: not a person using the tool (ignore it when comparing results)")
    log.debug("run=%s argv=%s", name, sys.argv)
    log.debug("python=%s (%s) exe=%s", platform.python_version(), platform.architecture()[0], sys.executable)
    log.debug("os=%s machine=%s", platform.platform(), platform.machine())
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    log.debug("config %s:\n%s", cfg.get("_path"), json.dumps(clean, indent=2))
    return log, log_file


def _install_excepthooks():
    def hook(exc_type, exc, tb):
        logging.getLogger("uncaught").critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        logging.getLogger("uncaught").critical(
            "Uncaught exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def _prune(log_dir, keep_last):
    logs = sorted(log_dir.glob("*.log"))
    for old in logs[:-keep_last] if keep_last and len(logs) > keep_last else []:
        try:
            old.unlink()
        except OSError:
            pass


def exit_now(code):
    """End the process for certain, once a camera tool has cleaned up: flush the log, then exit even if some library
    left a thread running, so the cameras and the camera lock are free for the next tool straight away.
    0 = finished normally (the launcher window closes), anything else = something went wrong (it stays open)."""
    import os
    import sys
    try:
        logging.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(int(code or 0))
