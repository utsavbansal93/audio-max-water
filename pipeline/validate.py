"""Validators that enforce the project's contracts.

- Faithful-wording: concatenating line.text values reproduces the source.
- Voice-consistency: every speaker has a cast.json entry, every voice_id
  is a real voice in the active backend.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.schema import CastModel, ScriptModel


_SPEAKER_LABEL_RE = re.compile(
    r"(?m)^\s*(?:Narrator|[A-Z][A-Za-z]{1,19}(?:\s[A-Z][A-Za-z]{1,19})?):\s*"
)
_STAGE_DIRECTION_RE = re.compile(r"\([^)]*\)")


def _normalize(s: str) -> str:
    """Whitespace-normalize, strip markdown syntax, speaker labels, and stage
    directions so both prose-form and script-form sources can be compared
    against the reconstructed-from-script.json text.

    Rules:
      - H2+ heading *lines* dropped entirely (structural chapter markers
        emitted by `RawStory.to_source_md()` for multi-chapter stories;
        they're JSON metadata, not spoken content).
      - H1 heading prefix (`# `) stripped; heading text kept (matches the
        existing convention where the book title is read aloud as the
        narrator's opening line).
      - *Italic by-line* (`*by Author*`) dropped.
      - Horizontal rules / scene separators dropped.
      - Speaker labels at line start (`Narrator:`, `Gatsby:`, `Mr. Darcy:`)
        stripped — they're attribution metadata, not spoken text.
      - Parentheticals `(…)` stripped — treated as stage directions that feed
        emotion.notes in script.json rather than being spoken. This is
        aggressive; it means prose with genuine parenthetical content would
        need a different source format.
      - Quotation marks (straight and curly) stripped.
      - Whitespace collapsed.
      - Lowercased.
    """
    # H2+ headings: drop the entire line (structural JSON metadata)
    s = re.sub(r"(?m)^\s*#{2,6}\s+.*$", "", s)
    # H1 heading prefix: strip `# ` but keep the text (book title is spoken)
    s = re.sub(r"(?m)^\s*#\s+", "", s)
    # Italic by-line (`*by Author*`) — match both as its own line in the
    # source AND inline in the reconstructed text (the LLM often keeps the
    # byline as narrator prose, which then concatenates with the next line).
    s = re.sub(r"\*by\s+[^*]+\*", "", s)
    s = re.sub(r"(?m)^\s*[\*\-_]{3,}\s*$", "", s)
    s = _SPEAKER_LABEL_RE.sub("", s)
    s = _STAGE_DIRECTION_RE.sub(" ", s)
    s = re.sub(r"[\u201c\u201d\u2018\u2019\"']", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def check_faithful_wording(script: ScriptModel, source_path: Path) -> list[str]:
    """Return a list of divergences (empty = pass)."""
    source = source_path.read_text(encoding="utf-8")
    reconstructed = " ".join(line.text for ch in script.chapters for line in ch.lines)

    ns = _normalize(source)
    nr = _normalize(reconstructed)

    if ns == nr:
        return []

    # Find the first divergence to give a helpful error.
    i = 0
    while i < min(len(ns), len(nr)) and ns[i] == nr[i]:
        i += 1
    window = 60
    src_snip = ns[max(0, i - window): i + window]
    rec_snip = nr[max(0, i - window): i + window]
    return [
        f"Faithful-wording divergence at normalized char {i}:",
        f"  source  : ...{src_snip}...",
        f"  script  : ...{rec_snip}...",
    ]


def check_voice_consistency(script: ScriptModel, cast: CastModel, valid_voice_ids: set[str]) -> list[str]:
    errors: list[str] = []
    speakers = {line.speaker for ch in script.chapters for line in ch.lines}
    for sp in speakers:
        if sp not in cast.mapping:
            errors.append(f"Speaker {sp!r} missing from cast.json")
        elif cast.mapping[sp] not in valid_voice_ids:
            errors.append(f"Cast {sp!r} -> {cast.mapping[sp]!r} is not a valid voice id for backend {cast.backend!r}")
    return errors


def check_main_character_voice_uniqueness(
    script: ScriptModel, cast: CastModel, main_threshold: int = 10,
) -> list[str]:
    """Enforce the CLAUDE.md cast-diligence rule: no two main characters share
    a resolved (backend, voice_id). Narrator is excluded (it's structurally
    one voice by design). A "main character" is a speaker with ≥ main_threshold
    dialogue lines in the script.

    Returns a list of error strings (one per collision bucket). Empty = OK.
    """
    from collections import Counter
    counts: Counter = Counter()
    for ch in script.chapters:
        for line in ch.lines:
            if line.speaker != "narrator":
                counts[line.speaker] += 1

    # Group main characters by their (backend, voice) bucket
    buckets: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for speaker, n in counts.items():
        if n < main_threshold:
            continue
        if speaker not in cast.mapping:
            continue  # already flagged by check_voice_consistency
        entry = cast.resolve(speaker)
        key = (entry.backend, entry.voice)
        buckets.setdefault(key, []).append((speaker, n))

    errors: list[str] = []
    for (backend, voice), members in buckets.items():
        if len(members) < 2:
            continue
        names = ", ".join(f"{sp} ({n} lines)" for sp, n in sorted(members, key=lambda x: -x[1]))
        errors.append(
            f"Main characters share voice {backend}:{voice!r} — {names}. "
            "Assign each a distinct voice (different Kokoro preset OR add a "
            "Chatterbox reference clip in voice_samples/ and route via cast.json)."
        )
    return errors


def load_script(path: Path) -> ScriptModel:
    return ScriptModel.model_validate(json.loads(path.read_text()))


def load_cast(path: Path) -> CastModel:
    return CastModel.model_validate(json.loads(path.read_text()))


if __name__ == "__main__":
    import sys
    script = load_script(Path(sys.argv[1]))
    source = Path(sys.argv[2])
    errs = check_faithful_wording(script, source)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)
    print("faithful-wording: OK")
