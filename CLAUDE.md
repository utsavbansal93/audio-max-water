# Project rules — Audio Max Water

Repo-local instructions. Every Claude Code session in this repo must follow these before declaring a task done.

## Logging discipline (non-negotiable)

Every change to this repo MUST update the relevant log **in the same turn as the change**, not after:

- **Code or behavior change** → add a `CHANGELOG.md` entry under `## [Unreleased]`.
- **Non-obvious choice** (picking one approach over another, rejecting a library, changing an abstraction) → add a numbered entry to `DECISIONS.md` with **Context / Options / Decision / Consequences**.
- **Anything worth retrospecting** (a false start, a surprising model behavior, a moment where the user made a judgment call, a failed experiment, a concept worth learning) → append to `STORY.md` as a dated narrative entry. Attribute decisions explicitly: "user chose X" vs "assistant chose X" and why.
- **Install / run / architecture change** → update the relevant `README.md` sections. If the change invalidates example commands, fix the examples.
- **Any render / tune / experiment** (new backend, new cast, new pause rule, new voice swap, anything that changes audio output) → run `python -m pipeline.bench --target '<label>' --notes '<short description>'` so a row is appended to `BENCHMARKS.md`. This is the performance time series for regression catching and retrospective analysis. Never skip it.

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

## Memory discipline (M-series 16 GB budget)

This project runs primarily on an M3 MacBook Air with 16 GB unified memory. Neural TTS backends have real memory costs that add up fast; on a machine where the working model set exceeds physical RAM, macOS swaps to SSD and the system crawls.

Approximate loaded-in-memory costs (April 2026):
- MLX Kokoro-82M-bf16: ~300 MB
- torch Kokoro-82M: ~500 MB
- Chatterbox-Turbo (0.5 B): ~1.5 GB + diffusion tensor buffers (~1 GB peak during sampling)
- faster-whisper base.en int8: ~200 MB

Rules:

1. **Never run more than one render process at a time.** A hybrid render already co-loads Kokoro + Chatterbox + Whisper. A second concurrent process doubles the footprint and trips swap.
2. **Do not background long-running Python processes without a reason.** `run_in_background: true` for a Chatterbox render leaves 2+ GB resident for the duration — easy to forget while starting new work.
3. **Kill Python processes between sessions.** `pgrep -f python3.12` before opening a new Claude Code session. Orphan processes from previous iterations accumulate.
4. **When memory is tight, split bench into render + qa.** The default `pipeline.bench` pipeline does render → QA with everything still loaded. Running `pipeline.render` and `pipeline.qa` as separate processes lets each release its models on exit.
5. **Chatterbox is the expensive one.** Kokoro-only renders have no memory concern on 16 GB. Chatterbox-heavy stories (many character lines) are where budget matters.

If the system memory starts swapping during a render, stop — let the swapper settle, split the work into smaller processes, resume. Don't power through.
