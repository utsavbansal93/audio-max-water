"""Voice audition — synthesize a short sample of a voice reading a line.

Used by the Voices screen to let users hear each proposed voice read
the *character's own line* before picking.

Caches results on disk at `~/.cache/audio-max-water/auditions/<hash>.wav`
so repeat plays are instant and crossing browsers / reloads doesn't
re-synthesize.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ui.services.backend_pool import get_backend, synth_lock


log = logging.getLogger(__name__)


CACHE_DIR = Path.home() / ".cache" / "audio-max-water" / "auditions"


def _audition_key(backend_name: str, voice_id: str, text: str) -> str:
    h = hashlib.sha1(f"{backend_name}::{voice_id}::{text}".encode()).hexdigest()[:16]
    return h


def audition(backend_name: str, voice_id: str, text: str) -> Path:
    """Return a WAV file path containing `text` rendered by `voice_id`.

    Shares a process-wide backend pool with cast + render so there's only
    one MLX / Chatterbox instance. Cached on disk.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _audition_key(backend_name, voice_id, text)
    out = CACHE_DIR / f"{key}.wav"
    if out.exists() and out.stat().st_size > 0:
        return out

    backend = get_backend(backend_name)
    with synth_lock():
        wav_bytes, _sr = backend.synthesize(text, voice_id)
    out.write_bytes(wav_bytes)
    log.debug("audition: synthesized %s / %s (%d bytes)", backend_name, voice_id, len(wav_bytes))
    return out


def clear_cache() -> int:
    """Remove cached auditions. Returns count removed. (Admin helper;
    not wired to the UI in MVP.)"""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for p in CACHE_DIR.glob("*.wav"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed
