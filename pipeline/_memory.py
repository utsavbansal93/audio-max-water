"""Memory watchdog for render/bench entry points.

Why it exists: a hybrid render co-loads Kokoro + Chatterbox + Whisper
(~4 GB peak). On a 16 GB Mac with a browser + Slack + OS open, starting
another render while one is already running trips SSD swap and the
system crawls. This module gates entry: if free RAM is below threshold
at start, the process refuses with a clear error.

Related:
  - CLAUDE.md "Memory discipline" — documents the per-backend rule.
  - BACKLOG.md #Supervisor — the eventual replacement (persistent model
    process + queue) that will make this guard unnecessary for most
    cases; that backlog entry includes a requirement to log RSS stats
    so we can relax the rule empirically once data exists.
"""
from __future__ import annotations


# Approximate loaded-in-memory cost per backend (GB) on M3 Apple Silicon.
# Used only to produce a helpful error message when the watchdog trips;
# enforcement is free-RAM-based, not budget-based, so these numbers don't
# need to be precise.
MEMORY_COST_GB: dict[str, float] = {
    "mlx-kokoro": 0.3,
    "kokoro":     0.5,
    "chatterbox": 2.5,   # model + diffusion tensor peaks during sampling
    "whisper":    0.3,   # faster-whisper base.en int8 inside QA
}


def available_gb() -> float:
    """Free RAM in GB (uses psutil's `available`, which accounts for
    reclaimable caches — closer to 'what a new process can actually get'
    than raw `free`)."""
    import psutil
    return psutil.virtual_memory().available / (1024 ** 3)


def require_free(min_gb: float = 4.0, backend: str | None = None) -> None:
    """Refuse to proceed if free RAM is below `min_gb`.

    Raises SystemExit with a message that (a) states the actual gap,
    (b) names the backend's typical cost if known, and (c) points at
    the fix (close apps / kill stale pythons / render smaller scope).
    """
    free = available_gb()
    if free >= min_gb:
        return

    expected = MEMORY_COST_GB.get(backend or "") if backend else None
    backend_hint = (
        f" (backend {backend!r} alone wants ~{expected:.1f} GB)"
        if expected else ""
    )
    raise SystemExit(
        f"Insufficient free RAM: {free:.1f} GB available, need ≥ {min_gb:.1f} GB"
        f"{backend_hint}. Running with less will trigger SSD swap and make the "
        f"system crawl. Close apps, kill lingering python processes "
        f"(`pgrep -f python3.12`), or render a smaller scope. "
        f"See CLAUDE.md 'Memory discipline'."
    )


# ----- Render-lock (B6) -------------------------------------------------------
#
# Prevents two concurrent renders on the same build dir, and (when any backend
# resolves to chatterbox) prevents any concurrent Chatterbox render on the
# machine. Uses fcntl.flock: kernel releases the lock on process exit even on
# SIGKILL, so no stale-lock-recovery needed. PID text inside the lock file is
# best-effort identification for the error message.

import fcntl
import os
from pathlib import Path as _Path

_held_locks: list = []  # module-global; fds kept alive for the process lifetime


def acquire_render_lock(build_dir, chatterbox: bool = False) -> None:
    """Acquire exclusive render locks or raise ConfigurationError.

    - Always acquires `<build_dir>/.render.lock`: one render per build dir.
    - If chatterbox=True, additionally acquires `<build_dir.parent>/.chatterbox.lock`:
      one Chatterbox render per machine (MPS is single-queue; parallel
      Chatterbox processes regress throughput by ~38% per Hyperthief data).

    On collision raises ConfigurationError naming the holder PID from the
    lock file's body text (may be stale if holder SIGKILLed and its PID was
    recycled; kernel still knows the correct holder via the fd).
    """
    from pipeline._errors import ConfigurationError

    build_dir = _Path(build_dir)
    paths = [build_dir / ".render.lock"]
    if chatterbox:
        paths.append(build_dir.resolve().parent / ".chatterbox.lock")

    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                holder = p.read_text().strip() or "unknown"
            except Exception:
                holder = "unknown"
            raise ConfigurationError(
                f"Another render is already running. Lock: {p} (holder PID: {holder}).",
                fix=f"Wait for it to finish, or `kill {holder}` if stale. "
                    f"Multiple concurrent Chatterbox renders serialize on MPS and regress throughput — "
                    f"see STORY.md parallelization retrospective.",
            )
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        _held_locks.append(fd)
