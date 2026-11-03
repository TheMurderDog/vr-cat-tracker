"""Per-run logging: every script logs to its own timestamped file under logs/ as well as the console."""

import datetime as _dt
import json
import logging
import platform
import sys
import threading

from .config import get, resolve_path

_FMT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(threadName)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def start_run(name, cfg):
    """Configure logging for this process and return (logger, log_file_path).

    Writes a header with the command line, Python, OS and the full config so a log
    file alone is enough to diagnose a run.
    """
    log_dir = resolve_path(get(cfg, "logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"{stamp}_{name}.log"

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
