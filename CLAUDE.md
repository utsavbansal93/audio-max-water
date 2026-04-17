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

## Cast diligence (non-negotiable)

After `pipeline.cast` writes `build/<stem>/cast.json`, and BEFORE calling `pipeline.render`: group characters by `gender` from `script.json`, count unique voice IDs per group. If any gender group has >1 main character (speaker with ≥10 lines) collapsed onto ≤ half as many voices as characters, **stop and surface it to the user** — either (a) swap voices manually via `pipeline.cast --swap`, or (b) switch affected characters to Chatterbox with reference clips in `voice_samples/` (mirroring `cast_gatsby.json`'s hybrid pattern).

Shipping audio where multiple main characters sound identical is a diligence failure, not a pipeline limitation. Kokoro's preset library has few same-gender distinct voices; collapse is the default outcome, not an edge case. The check is five seconds of inspection on `cast.json` and saves the user from discovering it only during playback. Applies to every multi-character render, short stories included — it bit us on Hyperthief (4670 words, 5 male mains → one preset) on 2026-04-17.

Until the P0 auto voice-sample search (see `BACKLOG.md`) lands, the orchestrator (Claude) does this check by hand and sources reference clips from LibriVox as a one-off.

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

1. **Render concurrency is per-backend, not global.** Kokoro-only renders (either `kokoro` or `mlx-kokoro`) can run up to 3 concurrent — each is ~0.5 GB. Any Chatterbox (or hybrid) render must be the only render process — Chatterbox is ~2.5 GB peak and leaves less than half of the 16 GB budget. Whisper QA adds ~0.3 GB to whatever else is running; prefer splitting `pipeline.render` and `pipeline.qa` into separate processes when memory is tight so each releases its models on exit.
2. **The memory watchdog (`pipeline/_memory.py::require_free`) runs at the top of every render/bench `main()`.** If free RAM is below 4 GB at start, the process refuses with a clear error. This catches "I forgot a render was running" cases automatically. You shouldn't need to think about it during normal work — only when it fires.
3. **Do not background long-running Python processes without a reason.** `run_in_background: true` for a Chatterbox render leaves 2+ GB resident for the duration — easy to forget while starting new work.
4. **Kill Python processes between sessions.** `pgrep -f python3.12` before opening a new Claude Code session. Orphan processes from previous iterations accumulate.
5. **Chatterbox is the expensive one.** Kokoro-only renders have no memory concern on 16 GB. Chatterbox-heavy stories (many character lines) are where budget matters.

If the system memory starts swapping during a render, stop — let the swapper settle, split the work into smaller processes, resume. Don't power through.

These rules are conservative. Once the supervisor pattern (see `BACKLOG.md`) accumulates real RSS stats across many renders, we can relax the rule empirically.
