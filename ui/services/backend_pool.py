"""Single shared TTS-backend cache for the UI process.

Loading MLX / Chatterbox twice in one process leaves MLX in a broken
state (manifests as `[Errno 32] Broken pipe` on the second caller's
synthesize). This module is the single source of backend instances
for cast proposal, audition, and render — they all load exactly once
per process and share the same object.

Thread-safe: a process-wide lock guards both load and synthesize, so
concurrent HTTP handlers and the render worker can't step on MLX
internals.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from tts import get_backend as _raw_get_backend
from tts.backend import TTSBackend


log = logging.getLogger(__name__)


_lock = threading.Lock()
_backends: dict[str, TTSBackend] = {}


def get_backend(name: str) -> TTSBackend:
    """Return a cached backend instance, loading on first use. Thread-safe."""
    with _lock:
        if name not in _backends:
            log.info("backend_pool: loading %s", name)
            _backends[name] = _raw_get_backend(name)
        return _backends[name]


def synth_lock() -> threading.Lock:
    """Process-wide lock held across a synthesize() call. Callers should:

        with synth_lock():
            wav, sr = backend.synthesize(...)

    Keeps MLX / Chatterbox internals from being touched concurrently.
    """
    return _lock


def loaded() -> list[str]:
    return list(_backends.keys())
