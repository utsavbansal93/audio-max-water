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
