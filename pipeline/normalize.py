"""Post-parse normalization — currently just: split lumped dialogue-attribution
tags so the attribution is on a narrator line rather than lumped with the
character's dialogue.

Why this exists: the LLM parser sometimes emits lines like

    {"speaker": "Rig", "text": "\"Hey!\" he said. \"Um, happy birthday?\""}

That renders as Rig speaking both the dialogue AND the "he said" attribution,
which sounds wrong — narrator attribution should be in the narrator's voice.
The prompt asks the LLM to split these but compliance varies. This step is
defense-in-depth: mechanical split that runs after every parse.

Preserves the faithful-wording contract via a per-line invariant check:
for any proposed split, `" ".join([p.text for p in parts]) == original.text`.
If mismatch (source had irregular whitespace), we skip that line and WARN —
the LLM-parsed line survives unchanged.
"""
from __future__ import annotations

import copy
import logging
from typing import Iterable

from pipeline._tags import (
    SANDWICHED_PRONOUN_TAG_RE,
    TRAILING_PRONOUN_TAG_RE,
    make_name_tag_regexes,
)
from pipeline.schema import ChapterModel, EmotionModel, LineModel, ScriptModel


log = logging.getLogger(__name__)


# Emotion attached to narrator attribution lines we insert. Neutral delivery,
# near-zero dwell — these are quick beats between fragments of the same
# speaker's dialogue, not weighted narration.
_NARR_TAG_EMOTION = EmotionModel(
    label="neutral",
    intensity=0.3,
    pace=0.0,
    notes="attribution tag (auto-split by pipeline.normalize)",
)


def _try_split(speaker: str, text: str) -> list[tuple[str, str]] | None:
    """Return fragment list `[(speaker, text), ...]` or None if no split applies.

    Tries the speaker-name pattern first (stricter: `<Name> said`), falls back
    to the pronoun pattern (`he/she/they said`). Pronoun fallback is gated to
    character-speaker lines only — narrator lines are presumed legitimate
    narration even when they contain pronoun-tag prose.
    """
    # Sandwiched with speaker name: `"A," Rig said, "B"`
    sandwich_name, trailing_name = make_name_tag_regexes(speaker)
    m = sandwich_name.match(text)
    if m:
        d1, tag, d2 = m.group("d1").rstrip(), m.group("tag").strip(), m.group("d2").strip()
        if d1 and tag and d2:
            return [(speaker, d1), ("narrator", tag), (speaker, d2)]

    m = trailing_name.match(text)
    if m:
        d1, tag = m.group("d1").rstrip(), m.group("tag").strip()
        if not tag.endswith("."):
            tag += "."
        if d1 and tag:
            return [(speaker, d1), ("narrator", tag)]

    # Sandwiched with pronoun: `"A," he said, "B"`
    m = SANDWICHED_PRONOUN_TAG_RE.match(text)
    if m:
        d1, tag, d2 = m.group("d1").rstrip(), m.group("tag").strip(), m.group("d2").strip()
        if d1 and tag and d2:
            return [(speaker, d1), ("narrator", tag), (speaker, d2)]

    m = TRAILING_PRONOUN_TAG_RE.match(text)
    if m:
        d1, tag = m.group("d1").rstrip(), m.group("tag").strip()
        if not tag.endswith("."):
            tag += "."
        if d1 and tag:
            return [(speaker, d1), ("narrator", tag)]

    return None


def _invariant_holds(original: str, parts: Iterable[tuple[str, str]]) -> bool:
    """The faithful-wording validator reconstructs by `" ".join(...)`.
    Our split must preserve that: joining the fragment texts with single
    spaces must yield the original line.text exactly. Catches cases where
    the LLM emitted non-space whitespace (tabs, multi-space, trailing
    newlines) inside the line — splitting would then drift from source.
    """
    return " ".join(text for _, text in parts) == original


def _split_line(line: LineModel) -> list[LineModel] | None:
    """Apply the splitter to one line; return list of new lines, or None
    if no split applies or the invariant fails."""
    if line.speaker == "narrator":
        return None
    parts = _try_split(line.speaker, line.text)
    if parts is None:
        return None
    if not _invariant_holds(line.text, parts):
        log.warning(
            "normalize: skipped split on [%s] %r — whitespace invariant failed",
            line.speaker, line.text[:80],
        )
        return None
    result: list[LineModel] = []
    for spk, text in parts:
        base = copy.deepcopy(line)
        new = base.model_copy(update={
            "speaker": spk,
            "text": text,
            "emotion": _NARR_TAG_EMOTION.model_copy() if spk == "narrator" else base.emotion,
        })
        result.append(new)
    return result


def canonicalize_speakers(script: ScriptModel) -> tuple[ScriptModel, int]:
    """Normalize speaker keys so the same character always uses one canonical
    casing across all chapters. First-seen spelling wins; subsequent variants
    (e.g. "rig" after "Rig") are rewritten to match.

    Prevents cast.json resolve misses and voice-uniqueness check bypasses when
    the LLM parser emits inconsistent capitalization across chapters.
    Returns the updated ScriptModel and the count of lines rewritten.
    """
    canon: dict[str, str] = {}  # lower → canonical
    # Pass 1: establish canonical spelling (first occurrence per character).
    for ch in script.chapters:
        for line in ch.lines:
            key = line.speaker.lower()
            if key not in canon:
                canon[key] = line.speaker

    # Pass 2: rewrite any deviant casings.
    n_fixed = 0
    new_chapters: list[ChapterModel] = []
    for ch in script.chapters:
        new_lines: list[LineModel] = []
        for line in ch.lines:
            canonical = canon.get(line.speaker.lower(), line.speaker)
            if canonical != line.speaker:
                line = line.model_copy(update={"speaker": canonical})
                n_fixed += 1
            new_lines.append(line)
        new_chapters.append(ch.model_copy(update={"lines": new_lines}))
    return script.model_copy(update={"chapters": new_chapters}), n_fixed


def split_lumped_dialogue_tags(script: ScriptModel) -> tuple[ScriptModel, int]:
    """Walk the script; for each character-speaker line that matches a lumped
    attribution pattern, split it into (dialogue, narrator tag, dialogue)
    — or (dialogue, narrator tag) for trailing tags.

    Returns the new ScriptModel and the count of split lines.
    """
    n_splits = 0
    new_chapters: list[ChapterModel] = []
    for ch in script.chapters:
        new_lines: list[LineModel] = []
        for line in ch.lines:
            split = _split_line(line)
            if split is None:
                new_lines.append(line)
                continue
            new_lines.extend(split)
            n_splits += 1
        new_chapters.append(ch.model_copy(update={"lines": new_lines}))
    return script.model_copy(update={"chapters": new_chapters}), n_splits
