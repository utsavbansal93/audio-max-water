"""Progress events emitted by long-running pipeline stages.

The web UI (Phase 2) consumes these via SSE; the CLI can log them.
The shape is deliberately small — enough to render a progress line and
optionally a per-line counter, nothing more.

`on_progress` callbacks in the render / orchestrator are always
`Optional[Callable[[ProgressEvent], None]]` with a safe None default,
so the CLI / existing callers don't break.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


Stage = str  # "ingest" | "parse" | "cast" | "render" | "qa" | "package"
Phase = str  # "start" | "progress" | "done" | "error"


@dataclass
class ProgressEvent:
    stage: Stage
    phase: Phase = "progress"
    message: str = ""
    current: int = 0        # e.g. line index within chapter (1-based)
    total: int = 0          # e.g. total lines in chapter
    chapter: int = 0        # 1-based; 0 = not applicable
    total_chapters: int = 0
    extra: dict | None = None

    def ratio(self) -> float:
        """Progress as a 0.0–1.0 ratio, or 0 if total is unknown."""
        return (self.current / self.total) if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        d = {
            "stage": self.stage,
            "phase": self.phase,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "chapter": self.chapter,
            "total_chapters": self.total_chapters,
            "ratio": self.ratio(),
        }
        if self.extra:
            d["extra"] = self.extra
        return d


ProgressCallback = Optional[Callable[[ProgressEvent], None]]


def emit(cb: ProgressCallback, event: ProgressEvent) -> None:
    """Safe invoke — no-op if cb is None, and callback exceptions are
    swallowed (progress reporting must never break a render)."""
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        # A logger would be ideal here, but importing logging would cycle
        # with modules that use logging + events together. Silent is fine
        # — callbacks are fire-and-forget.
        pass
