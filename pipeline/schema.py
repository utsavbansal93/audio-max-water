"""Pydantic models mirroring the script.json / cast.json schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    book_context: str = "none"
    characters: list[CharacterModel]
    chapters: list[ChapterModel]


class CastModel(BaseModel):
    """character_name -> voice_id. Authoritative; never regenerated implicitly."""
    backend: str
    mapping: dict[str, str]
