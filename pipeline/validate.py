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


def _normalize(s: str) -> str:
    """Whitespace-normalize, strip markdown syntax (but keep heading text)."""
    # Strip leading '#' chars from headings but keep the text itself, so the
    # narrator can speak chapter titles and still match the source.
    s = re.sub(r"(?m)^\s*#{1,6}\s+", "", s)
    # Drop horizontal rules / scene separators.
    s = re.sub(r"(?m)^\s*[\*\-_]{3,}\s*$", "", s)
    # Drop quotation marks — dialogue attribution strips them when splitting
    # lines into speaker-tagged pieces.
    s = re.sub(r"[\u201c\u201d\u2018\u2019\"']", "", s)
    # Collapse whitespace.
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
