"""Pipeline logging setup.

Two handlers:
  - Console: INFO and above, human-friendly single-line records.
  - File:    DEBUG and above, full context + exceptions, rotated per run.

The file handler is only attached when `configure_logging(build_dir=...)`
is called with a concrete directory — so `python -m pipeline.parse`
ad-hoc runs don't litter the repo with stray logs; `pipeline.run` runs
always get one at `<build>/run.log`.

All pipeline modules use `logging.getLogger(__name__)`. Call
`configure_logging` once at the top of a CLI entry point.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


_CONSOLE_FMT = "%(asctime)s %(levelname)-5s  %(message)s"
_FILE_FMT = "%(asctime)s %(levelname)-5s %(name)-28s %(message)s"
_DATE_FMT = "%H:%M:%S"


class _RelativeTimeFilter(logging.Filter):
    """Console shows `[+12.3s]` relative to configure_logging() — easier
    to scan than wall-clock when you're reading a single run's output."""

    def __init__(self) -> None:
        super().__init__()
        import time
        self._t0 = time.monotonic()

    def filter(self, record: logging.LogRecord) -> bool:
        import time
        dt = time.monotonic() - self._t0
        record.asctime = f"[+{dt:6.1f}s]"
        return True


def configure_logging(
    *,
    build_dir: Optional[Path] = None,
    verbose: bool = False,
    quiet: bool = False,
) -> Optional[Path]:
    """Set up the root pipeline logger.

    Returns the log file path if a file handler was attached, else None.
    Safe to call multiple times — clears prior handlers first.
    """
    logger = logging.getLogger("pipeline")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    # Console handler
    console = logging.StreamHandler(stream=sys.stderr)
    console_level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
    console.addFilter(_RelativeTimeFilter())
    logger.addHandler(console)

    # Also configure sibling loggers we control so their messages flow
    # through the same handlers.
    for sibling in ("llm",):
        sib = logging.getLogger(sibling)
        sib.handlers = []
        sib.setLevel(logger.level)
        sib.propagate = False
        sib.addHandler(console)

    log_path: Optional[Path] = None
    if build_dir is not None:
        build_dir = Path(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        log_path = build_dir / "run.log"
        file_h = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_h.setLevel(logging.DEBUG)
        file_h.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(file_h)
        for sibling in ("llm",):
            logging.getLogger(sibling).addHandler(file_h)
        logger.debug("log file attached at %s", log_path)
    return log_path


def log_exception(logger: logging.Logger, message: str, exc: BaseException) -> None:
    """One-line ERROR to console + full traceback to the DEBUG file."""
    logger.error("%s: %s", message, exc)
    logger.debug("%s — full traceback:", message, exc_info=exc)
