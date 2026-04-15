"""TTS backend factory.

Pipeline code uses: `tts.get_backend(name)` — never imports a concrete
backend. Adding an engine = one file + one line here.
"""
from __future__ import annotations

from typing import Any

from .backend import Emotion, TTSBackend, Voice


def get_backend(name: str, **kwargs: Any) -> TTSBackend:
    name = name.lower().strip()
    if name == "kokoro":
        from .kokoro_backend import KokoroBackend
        return KokoroBackend(**kwargs)
    if name == "chatterbox":
        from .chatterbox_backend import ChatterboxBackend  # noqa: PLC0415
        return ChatterboxBackend(**kwargs)
    if name == "xtts":
        from .xtts_backend import XTTSBackend  # noqa: PLC0415
        return XTTSBackend(**kwargs)
    raise ValueError(f"Unknown backend: {name!r}. Known: kokoro, chatterbox, xtts")


__all__ = ["TTSBackend", "Voice", "Emotion", "get_backend"]
