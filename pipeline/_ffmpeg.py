"""Centralised ffmpeg / ffprobe binary resolution.

Resolve once at import time; every pipeline module imports from here rather
than each calling shutil.which() independently (and definitely not inside
loops).
"""
from __future__ import annotations

import shutil

FFMPEG  = shutil.which("ffmpeg")  or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
