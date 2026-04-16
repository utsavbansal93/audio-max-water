"""Pydantic models mirroring the script.json / cast.json schemas."""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator


class EmotionModel(BaseModel):
    label: str = "neutral"
    intensity: float = Field(0.4, ge=0.0, le=1.0)
    pace: float = Field(0.0, ge=-1.0, le=1.0)
    notes: str = ""


class LineModel(BaseModel):
    speaker: str
    text: str
    emotion: EmotionModel = EmotionModel()


class CharacterModel(BaseModel):
    name: str
    age_hint: str = "adult"
    gender: Literal["male", "female", "neutral"] = "neutral"
    accent: str = "unspecified"
    personality: str = ""
    sample_lines: list[str] = Field(default_factory=list)


class ChapterModel(BaseModel):
    number: int
    title: str
    lines: list[LineModel]


class ScriptModel(BaseModel):
    title: str
    author: str = "unknown"
    language: str = "en"
    book_context: str = "none"
    characters: list[CharacterModel]
    chapters: list[ChapterModel]


class CastEntry(BaseModel):
    """Per-character voice + backend assignment.

    Expanded form of the cast mapping introduced when we added the
    hybrid-engine pattern (Kokoro for narrators, Chatterbox for emotional
    characters). Bare strings in cast.json are still accepted for
    backward-compatibility — they resolve to (voice=<str>, backend=<CastModel.backend>).
    """
    voice: str               # voice id (kokoro preset, or a reference-clip stem for chatterbox)
    backend: str = "kokoro"  # which engine renders this character


class CastModel(BaseModel):
    """character -> voice assignment. Authoritative; never regenerated implicitly.

    The mapping values can be either:
      - a bare string (legacy): "<voice_id>" → resolves to this cast's default backend
      - a CastEntry: {"voice": ..., "backend": ...} → explicit per-character engine
    """
    backend: str                                            # default engine for bare-string entries
    mapping: dict[str, Union[str, CastEntry]]

    def resolve(self, character: str) -> CastEntry:
        """Return the concrete (voice, backend) for a character, applying the
        bare-string backward-compat shim."""
        val = self.mapping[character]
        if isinstance(val, str):
            return CastEntry(voice=val, backend=self.backend)
        return val
