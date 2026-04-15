"""Abstract TTS backend — the swappability contract.

Every engine implements this interface. The pipeline (pipeline/render.py)
depends on this module only, never on a concrete backend.

The Emotion dataclass is a *superset* — engines silently ignore fields they
don't support. This keeps script.json backend-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


EmotionLabel = Literal[
    "neutral", "calm", "tender", "warm", "joy", "excited", "wry", "dry",
    "melancholic", "sad", "anxious", "embarrassed", "humbled",
    "angry", "firm", "commanding", "whisper", "urgent", "resolute",
    "vulnerable", "hopeful", "awkward", "formal",
]


@dataclass
class Emotion:
    """What the actor should do with this line.

    intensity: 0.0 = subdued, 1.0 = theatrical. Engines that don't support
    explicit emotion (Kokoro) use this as a hint for phrasing only.
    pace: -1.0 = slower than default, +1.0 = faster.
    """
    label: EmotionLabel = "neutral"
    intensity: float = 0.4
    pace: float = 0.0
    notes: str = ""  # optional free-text direction for the actor; LLM-based engines may use this


@dataclass
class Voice:
    """A voice the backend can produce. id is what cast.json references."""
    id: str
    display_name: str
    gender: Literal["male", "female", "neutral"] = "neutral"
    age: Literal["child", "young", "adult", "mature", "old"] = "adult"
    accent: str = "en-US"
    tags: list[str] = field(default_factory=list)  # e.g. ["warm", "authoritative"]


class TTSBackend(ABC):
    """Abstract TTS engine."""

    name: str = "abstract"

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """Return all voices this backend can produce."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: Optional[Emotion] = None,
        speed: float = 1.0,
    ) -> tuple[bytes, int]:
        """Render text → (WAV bytes, sample_rate).

        Implementations:
          - must honour voice_id exactly (no implicit substitution)
          - should use emotion where supported, ignore silently otherwise
          - must be deterministic for the same (text, voice_id, emotion, speed,
            seed) — the pipeline relies on this for cache-busting.
        """

    @abstractmethod
    def supports_emotion(self) -> bool:
        """True if the backend meaningfully uses Emotion (beyond phrasing)."""

    def requires_reference_audio(self) -> bool:
        """True for cloning backends (Chatterbox, XTTS). Default: False."""
        return False
