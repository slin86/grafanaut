"""Logging helpers.

Besides the usual formatting this module keeps a global count of emitted
ERROR records. main() uses it to return a non-zero exit code, so that a CI
pipeline actually turns red when a restore partially failed instead of
logging the error and reporting success.
"""

import logging


class _ErrorCounter(logging.Handler):
    """Counts ERROR (and above) records across all grafanaut loggers."""

    count = 0

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            _ErrorCounter.count += 1


_counter = _ErrorCounter()


def setup_logger(name: str = "grafanaut", level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        # Avoid stacking duplicate handlers when a module is imported twice.
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(_counter)
    logger.propagate = False

    return logger


def error_count() -> int:
    return _ErrorCounter.count


def reset_error_count() -> None:
    _ErrorCounter.count = 0
