# Project rules — Audio Max Water

Repo-local instructions. Every Claude Code session in this repo must follow these before declaring a task done.

## Logging discipline (non-negotiable)

Every change to this repo MUST update the relevant log **in the same turn as the change**, not after:

- **Code or behavior change** → add a `CHANGELOG.md` entry under `## [Unreleased]`.
- **Non-obvious choice** (picking one approach over another, rejecting a library, changing an abstraction) → add a numbered entry to `DECISIONS.md` with **Context / Options / Decision / Consequences**.
- **Anything worth retrospecting** (a false start, a surprising model behavior, a moment where the user made a judgment call, a failed experiment, a concept worth learning) → append to `STORY.md` as a dated narrative entry. Attribute decisions explicitly: "user chose X" vs "assistant chose X" and why.
- **Install / run / architecture change** → update the relevant `README.md` sections. If the change invalidates example commands, fix the examples.

Do not defer log updates "to the end" — writing them live captures real-time reasoning, not post-hoc reconstruction.

## Faithful-wording contract

The `text` field in `script.json` is **byte-verbatim** from the source story. Opus parsing MUST NOT paraphrase dialogue. A validator (`pipeline/validate.py`) reconstructs the story from `script.json` and diffs against the source — pipeline aborts on any non-whitespace divergence.

## Voice consistency contract

`cast.json` is the **single source of truth** for `character → voice_id` mapping. Never regenerate it implicitly. If a character needs a different voice, update `cast.json` explicitly and re-render only affected lines.

## Backend swappability contract

`pipeline/render.py` must never import a concrete TTS backend. It always goes through `tts.get_backend(name)` and the `TTSBackend` ABC. Adding a new engine = one file in `tts/`, zero pipeline changes.

## Environment

- Python: `.venv/bin/python` (Python 3.12, created from `/opt/homebrew/opt/python@3.12/bin/python3.12`)
- ffmpeg: `/opt/homebrew/bin/ffmpeg`
- Working backend models live under `~/.cache/` (Hugging Face, torch hub) — do not commit.
- `build/`, `out/`, `voice_samples/` (except `.gitkeep`), `samples/`, and `.venv/` are gitignored.
