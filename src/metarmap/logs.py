"""
Where the map's log goes. Every module logs with the standard library: log = logging.getLogger(__name__).

configure() is called once, when the map starts (app.main): everything at INFO and above goes to metarmap.log (in the
folder the map runs from, rotated), and warnings and errors also go to the console, which systemd keeps in the
journal (journalctl -u metarmap). Until then nothing is set up, so importing the package (tests, tools) writes no
file: pytest's caplog sees the records instead.
"""

import logging
import logging.handlers
import sys

LOG_NAME = "metarmap"  # the package's logger: every module's logger is under it (metarmap.metar, ...)
LOG_FILE = "metarmap.log"
MAX_BYTES = 10 * 1024 * 1024  # each file; LOG_FILE.1, .2, ... are the older ones
BACKUP_COUNT = 10
FORMAT = "%(asctime)s %(levelname)s %(name)s.%(funcName)s:%(lineno)d: %(message)s"


def configure(path=LOG_FILE, console=None, level=logging.INFO) -> logging.Logger:
    """
    Sends the map's log to `path` (everything at `level` and above) and its warnings and errors to `console`
    (default: stderr). Calling it again replaces the handlers it added, so nothing is logged twice.
    """
    logger = logging.getLogger(LOG_NAME)
    for handler in [h for h in logger.handlers if getattr(h, "_metarmap", False)]:
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(FORMAT)

    to_file = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT)
    to_console = logging.StreamHandler(console if console is not None else sys.stderr)
    to_console.setLevel(logging.WARNING)
    for handler in (to_file, to_console):
        handler.setFormatter(formatter)
        handler._metarmap = True
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False  # the map's own handlers only: not also the root logger's, if a library set one up
    return logger
