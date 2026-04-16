"""Cast characters to voices. Generate audition samples.

Workflow:
    python -m pipeline.cast --propose       # writes cast.json + samples/<character>/*.wav
    python -m pipeline.cast --swap Darcy 2  # promote the ranked #2 proposal to #1
    python -m pipeline.cast --approve       # freeze cast.json

cast.json is the single source of truth for character -> voice. Do not
regenerate implicitly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from pipeline.schema import CastModel, CharacterModel, ScriptModel
from tts import get_backend
from tts.backend import TTSBackend, Voice


REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO / "config.yaml").read_text())


# --- voice-scoring heuristic --------------------------------------------------

def _score(character: CharacterModel, voice: Voice) -> float:
    """Rank a voice against a character. Higher is better.

    Intentionally simple — this is a first pass, tuned by listening.
    The LLM-driven caster (future) can replace this with a reasoned choice,
    but a deterministic fallback is valuable for reproducibility.
    """
    score = 0.0

    # Gender match is near-decisive for dialogue naturalness.
    if character.gender == voice.gender:
        score += 4.0
    elif voice.gender == "neutral":
        score += 0.5

    # Accent match matters a lot for period fiction (P&G -> en-GB).
    char_accent = (character.accent or "").lower()
    voice_accent = voice.accent.lower()
    if char_accent and char_accent == voice_accent:
        score += 3.0
    elif char_accent.startswith("en-") and voice_accent.startswith("en-"):
        score += 0.5  # wrong English still better than completely off

    # Age hint.
    age_hint = (character.age_hint or "").lower()
    age_map = {"teen": "young", "20s": "young", "30s": "adult", "40s": "adult",
               "50s": "mature", "60s": "mature", "70s": "old",
               "young": "young", "middle-aged": "adult", "elderly": "old"}
    want_age = next((age_map[k] for k in age_map if k in age_hint), None)
    if want_age and want_age == voice.age:
        score += 1.5

    # Tag overlap with personality keywords.
    personality_words = set(character.personality.lower().split())
    tag_hits = sum(1 for t in voice.tags if t in personality_words)
    score += 0.8 * tag_hits

    # Narrator bonus: prefer voices tagged "narrator" for the narrator role.
    if character.name == "narrator" and "narrator" in voice.tags:
        score += 2.0

    return score


def _propose_for_character(character: CharacterModel, voices: list[Voice]) -> list[Voice]:
    """Top-3 voices for this character, best first."""
    ranked = sorted(voices, key=lambda v: _score(character, v), reverse=True)
    return ranked[:3]


# --- sample rendering ---------------------------------------------------------

def _sample_text_for(character: CharacterModel) -> str:
    """Pick an audition line for this character."""
    if character.sample_lines:
        # Prefer the second-longest — long enough to hear timbre, short enough to iterate on.
        lines = sorted(character.sample_lines, key=len, reverse=True)
        return lines[min(1, len(lines) - 1)]
    if character.name == "narrator":
        return "She looked at him, and wondered what he might say next."
    return "I think I shall take the long way home today."


def _render_sample(backend: TTSBackend, text: str, voice_id: str, out_path: Path) -> None:
    wav_bytes, sr = backend.synthesize(text, voice_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(wav_bytes)
    # Sanity: the caller can inspect sr via the WAV header.
    _ = sr


# --- main ---------------------------------------------------------------------

def propose(
    script_path: Path,
    out_dir: Path,
    backend_name: str,
    *,
    backend: TTSBackend | None = None,
) -> tuple[CastModel, dict[str, list[Voice]]]:
    """Propose a cast for the script. Optionally accepts a pre-built
    backend so the UI's shared backend-pool can be reused — avoids
    loading MLX / Chatterbox twice in one process."""
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    if backend is None:
        backend = get_backend(backend_name)
    voices = backend.list_voices()

    proposals: dict[str, list[Voice]] = {}
    mapping: dict[str, str] = {}

    out_dir.mkdir(parents=True, exist_ok=True)
    for ch in script.characters:
        top = _propose_for_character(ch, voices)
        proposals[ch.name] = top
        mapping[ch.name] = top[0].id
        # Render an audition per proposed voice.
        sample_text = _sample_text_for(ch)
        for rank, v in enumerate(top, start=1):
            out_wav = out_dir / ch.name / f"{rank}_{v.id}.wav"
            _render_sample(backend, sample_text, v.id, out_wav)

    cast = CastModel(backend=backend_name, mapping=mapping)
    return cast, proposals


def write_cast(cast: CastModel, path: Path) -> None:
    path.write_text(json.dumps(cast.model_dump(), indent=2) + "\n")


def load_cast(path: Path) -> CastModel:
    return CastModel.model_validate(json.loads(path.read_text()))


def print_proposals(proposals: dict[str, list[Voice]], cast: CastModel, samples_dir: Path) -> None:
    print(f"\nProposed cast ({cast.backend}):\n")
    for character, top in proposals.items():
        print(f"  {character}:")
        for rank, v in enumerate(top, start=1):
            marker = "★" if v.id == cast.mapping[character] else " "
            tags = ", ".join(v.tags) if v.tags else "-"
            print(f"    {marker} {rank}. {v.display_name:<18} [{v.gender}, {v.age}, {v.accent}]  tags: {tags}")
    print(f"\nSamples in: {samples_dir}")
    print("  Play any: afplay <path>  |  Open folder: open", samples_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="build/script.json", type=Path)
    ap.add_argument("--cast",   default="cast.json",         type=Path)
    ap.add_argument("--samples-dir", default="samples/cast", type=Path)
    ap.add_argument("--backend", default=CFG["backend"])
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--propose", action="store_true")
    sub.add_argument("--approve", action="store_true")
    sub.add_argument("--swap", nargs=2, metavar=("CHARACTER", "RANK"))
    args = ap.parse_args()

    if args.propose:
        cast, proposals = propose(args.script, args.samples_dir, args.backend)
        write_cast(cast, args.cast)
        print_proposals(proposals, cast, args.samples_dir)
        print("\nCast written to", args.cast, "(pending approval)")
        return

    if args.approve:
        cast = load_cast(args.cast)
        print(f"Approved cast ({cast.backend}):")
        for c, v in cast.mapping.items():
            print(f"  {c:<20} -> {v}")
        return

    if args.swap:
        character, rank_s = args.swap
        rank = int(rank_s)
        # Re-derive proposals deterministically to find rank N.
        script = ScriptModel.model_validate(json.loads(args.script.read_text()))
        backend = get_backend(args.backend)
        voices = backend.list_voices()
        ch = next((c for c in script.characters if c.name == character), None)
        if ch is None:
            raise SystemExit(f"No such character in script: {character!r}")
        top = _propose_for_character(ch, voices)
        if rank < 1 or rank > len(top):
            raise SystemExit(f"Rank out of range (1..{len(top)})")
        cast = load_cast(args.cast)
        old = cast.mapping.get(character)
        cast.mapping[character] = top[rank - 1].id
        write_cast(cast, args.cast)
        print(f"{character}: {old} -> {top[rank - 1].id} (rank {rank})")


if __name__ == "__main__":
    main()
