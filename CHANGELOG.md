# Changelog

All notable changes to this project will be documented here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Validator `_normalize` now preserves heading text (strips only the `#` prefix) and drops quotation marks (Unicode curly + straight), so dialogue attribution that splits lines doesn't fail the faithful-wording check.
- `.gitignore` uses `**` double-glob for `build/`, `out/`, `samples/`, `voice_samples/` — previous single-level globs missed nested sample WAVs.
- Cast swapped per listening test: `narrator`→`bf_isabella`, `Darcy`→`bm_lewis`, `Elizabeth`→`bf_emma`.
- `pipeline/render.py::_pause_for` is now emotion-aware: speaker-change gets 2.2× base gap, high-intensity lines add a held-breath approach, prior weighty lines add a ring-out, slow-pace lines add approach time.
- `tts/kokoro_backend.py` widened pace→speed coefficient (0.175 → 0.28) and added a small intensity-driven deceleration on weighty lines, so `pace: -0.3` is now audibly slower.
- `build/script.json` split Darcy's two long paragraphs into 4 fragments each with per-beat intensity/pace, and split the final narrator paragraph at the ellipsis — gives Kokoro room to re-attack between rhetorical beats instead of flat-lining through long Austen sentences.

### Added
- Initial project scaffolding: `tts/`, `pipeline/`, `prompts/`, `stories/`, `build/`, `voice_samples/`, `out/`, `ui/`, `samples/`.
- `CLAUDE.md` — project rules enforcing logging discipline, faithful-wording contract, voice-consistency contract, backend-swappability contract.
- `README.md` — install, usage, engine-swap docs.
- `DECISIONS.md`, `STORY.md` — initial entries covering engine selection and build kickoff.
- Python 3.12 venv with Kokoro TTS installed and smoke-tested; espeak-ng installed via brew.
- `tts/backend.py` — `TTSBackend` ABC with `Voice`, `Emotion` dataclasses.
- `tts/kokoro_backend.py` — Kokoro wrapper with 54 preset voices exposed.
- `tts/__init__.py` — `get_backend(name)` factory.
- `prompts/parse_story.md` — story parsing contract (book-context block, faithful-wording rule).
- `prompts/cast_voices.md` — voice-casting reasoning prompt.
- `pipeline/script.py` — story → `script.json` via Opus (or manual for tests).
- `pipeline/cast.py` — propose / approve / swap voice casting.
- `pipeline/render.py` — script + cast → per-line WAVs + chapter MP3.
- `pipeline/package.py` — MP3s → `.m4b` with chapter markers.
- `pipeline/validate.py` — faithful-wording check, voice-consistency check.
- `stories/pp_final_reconciliation.md` — P&P Chapter 58 excerpt for the engine comparison test.
- `config.yaml` — backend selection, output settings, seeds.
- `.gitignore`, `pyproject.toml`.
