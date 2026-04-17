"""Canonical line-cache key.

Both pipeline.render and pipeline._short_line_splitter install WAV files
keyed by this hash.  Keeping the implementation here prevents silent cache-
seat collisions if the key format ever changes — update once, both modules
pick it up automatically.
"""
from __future__ import annotations

import hashlib

from pipeline.schema import LineModel


def line_hash(line: LineModel, voice_key: str) -> str:
    """Return a 12-hex-char cache key for a rendered line.

    `voice_key` is ``"<backend>:<voice_id>"``.  The key covers all fields
    that affect audio output: text, voice, and emotion label/intensity/pace/
    notes.  Switching to a tuple-string avoids json.dumps overhead (≈300
    serialisations per Hyperthief-length render).
    """
    payload = (
        f"{line.text}\x00"
        f"{voice_key}\x00"
        f"{line.emotion.label}\x00"
        f"{line.emotion.intensity}\x00"
        f"{line.emotion.pace}\x00"
        f"{line.emotion.notes or ''}"
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:12]
