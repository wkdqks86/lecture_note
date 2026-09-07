import faulthandler
import sys
import threading
import traceback
from datetime import datetime

from app.paths import DATA_DIR

LOG_PATH = DATA_DIR / "crash.log"

# Kept alive for the process lifetime: faulthandler writes into this handle
# from a signal/abort context, so it must not be closed or garbage collected.
_log_file = None


def _write(header: str, text: str) -> None:
    if _log_file is None:
        return
    _log_file.write(f"\n===== {header} @ {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    _log_file.write(text)
    _log_file.flush()


def install() -> None:
    """Leaves a trace when the app dies without saying anything.

    The exe is built windowed (no console), so both kinds of silent death --
    a hard abort (e.g. Qt tearing down a still-running QThread) and an
    unhandled Python exception inside a Qt slot, which PySide6 turns into a
    process exit -- previously vanished without a single message. Both now
    land in crash.log next to the user's data."""
    global _log_file
    if _log_file is not None:
        return

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    except OSError:
        return  # logging must never be the thing that breaks startup

    faulthandler.enable(file=_log_file)

    def excepthook(exc_type, exc_value, exc_tb):
        _write("unhandled exception", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def thread_excepthook(args):
        _write(
            f"unhandled exception in thread {args.thread.name if args.thread else '?'}",
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
