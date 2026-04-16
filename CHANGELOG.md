# Changelog

All notable changes to this project will be documented here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- `pipeline/package.py` — two metadata bugs: (1) `--script` defaulted to `build/script.json` regardless of `--build`, causing chapter titles to bleed from whichever story last used the default build dir; default is now `<build>/script.json` so `--build` is the single required arg. (2) `ffmetadata` never wrote `artist=`, producing "Unknown author" in all players; `--author` flag added and wired into the metadata block.

### Added
- `tts/chatterbox_backend.py` — Chatterbox TTS backend (Resemble AI, autoregressive Llama-0.5B backbone). Maps `Emotion.intensity` → `exaggeration` (0.30–0.95 range), uses reference clips from `voice_samples/<voice_id>.wav`, post-processes pace via ffmpeg `atempo`. Model loaded once in `__init__` per the MLX pattern. Includes `install_clean_exit_hook()` — a workaround for a SIGBUS crash in `_sentencepiece.cpython-312-darwin.so` during Python shutdown; registers an atexit `os._exit(0)` to bypass the bad destructor path. Without it, macOS shows a "Python quit unexpectedly" dialog after every successful render.
- `voice_samples/gatsby_ref.wav` + `voice_samples/daisy_ref.wav` — reference clips extracted from LibriVox Version 5 (Dramatic Reading) of *The Great Gatsby* Chapter 5: Tomas Peter as Gatsby at 1083.8–1091.7s (house description, 7.9s single-voice), Jasmin Salma as Daisy at 1343.5–1352.8s (shirts-scene tears, 9.3s single-voice). Timestamps located via `faster-whisper` word-level alignment against known script lines.
- `voice_samples/SOURCES.md` — PD attribution, file provenance, extraction commands, and the alignment methodology for reproducibility.
- `CastEntry` model in `pipeline/schema.py` — `{voice, backend}` per-character assignment. `CastModel.mapping` is now `dict[str, str | CastEntry]` with a `.resolve(character)` helper that applies the bare-string → default-backend shim for backward compatibility with existing P&P casts.
- Per-speaker backend resolution in `pipeline/render.py`: `_get_backend_cached` lazy-loads each backend once; `render_chapter` dispatches per line based on `cast.resolve(speaker).backend`. A chapter with mixed engines pays each engine's load cost exactly once.
- Hybrid cast for Gatsby: `cast_gatsby.json` updated — narrator stays on Kokoro (`am_michael`), Gatsby uses `gatsby_ref` on Chatterbox, Daisy uses `daisy_ref` on Chatterbox.
- `BACKLOG.md` — deferred follow-ups with the reason each is deferred. Covers Sesame CSM (next-gen engine), Dia (inline emotion tags), LLM-driven casting, web UI, expanded reference library, and QA-threshold calibration.
- `stories/salt-and-rust.md` + `build_salt_and_rust/script.json` + `cast_salt_and_rust.json` — *Salt and Rust*, original post-apocalyptic short story. Three-character cast: narrator (`bm_george`), Furiosa (`af_nicole`), Mariner (`am_echo`). Production notes supplied with full voice direction, pacing, and emotion annotations per line.
- `build_salt_and_rust/config.yaml` — first use of per-story config override pattern. Sets `scene_pause_ms: 2000` per production direction; global `config.yaml` unchanged.
- `pipeline/config.py` — new `load_config(build_dir)` utility. Deep-merges `<build_dir>/config.yaml` over global `config.yaml` when present. Enables per-story config without touching global defaults.
- `pipeline/render.py` — scene-break handling: `render_chapter` detects `"---"` lines and injects `scene_pause_ms` silence instead of synthesizing — wires up the previously-defined-but-unused `scene_pause_ms` config key. `render_all` calls `load_config(build_dir)` so per-story overrides flow into pause/render logic.

### Removed
- `.gitignore` no longer ignores `cast*.json` (authored configuration, belongs in history). A stray `script.json` at the repo root stays ignored as a safety net via `/script.json`; build-dir script files (`build*/script.json`) are tracked by the allow-list.

### Changed
- `README.md` rewritten as user-facing — audience is someone landing on the repo cold who wants to turn a story into an audiobook. New sections: one-paragraph what-is-this, Quickstart, Source formats, How it works, Casting, Swapping engines, **Modifying for your system** (Linux / NVIDIA CUDA / CPU-only / Windows — covers which parts are Mac-specific vs cross-platform), Troubleshooting, Project docs, License. AI-assistant instructions moved out — they live in `CLAUDE.md`; README now links.
- Portability refactor: `pipeline/render.py`, `pipeline/package.py`, `pipeline/qa.py`, `pipeline/bench.py` replace hard-coded `/opt/homebrew/bin/ffmpeg` / `/opt/homebrew/bin/ffprobe` with `shutil.which(...)` so the code runs on any platform where the binaries are on `$PATH`. Falls back to the Homebrew paths only if `shutil.which` returns `None`.
- `.gitignore` rewritten to ignore regenerable build artifacts (per-line WAVs, silence clips, chapter MP3s, concat metadata) across every `build*/` directory while keeping `build*/script.json` tracked — the script is the authored parse output and belongs in history.

### Reverted
- Drama-amp iteration (commit `429179c`) reverted via `b852045` after user confirmed the changes did not bring emotion to Kokoro's American voices. The fundamental issue is Kokoro's non-autoregressive architecture — no emotional-state input — which structural prosody (pauses, pace, contrast) cannot compensate for. See `DECISIONS.md #0011` for the escalation decision.

### Added
- `stories/gatsby_west_egg_reunion.md` + `build_gatsby/script.json` + `cast_gatsby.json` — Great Gatsby reunion scene (Chapter 5). First non-Austen source, first script-format source (`Narrator:` / `Gatsby:` / `(stage direction)` style), first American-English cast. Cast: narrator (Nick) → `am_michael`, Gatsby → `am_onyx`, Daisy → `af_heart`. Per-book cast file pattern established: `cast_<book>.json` for each distinct book's voice map; the default `cast.json` remains the P&P cast.
- `pipeline/validate.py::_normalize` extended to handle script-format sources: strips speaker labels (`^Narrator:\s*`, `^Gatsby:\s*`, etc.) and parenthetical stage directions `(…)` before diffing. Existing prose-form scenes (Austen) still validate because neither feature is present there.
- `tts/mlx_kokoro_backend.py` — new backend using [mlx-audio](https://github.com/Blaizzy/mlx-audio) with `mlx-community/Kokoro-82M-bf16` weights. Same Kokoro voices/weights, MLX inference path for Apple Silicon. Model loaded once in `__init__` (passing an instance to `generate_audio` avoids the per-call reload that made our first MLX run 2× slower).
- `config.yaml` backend flipped to `mlx-kokoro`; `pipeline/render.py` now resolves backend as `explicit-arg > config.yaml > cast.backend` so `cast.json` produced under `kokoro` reuses cleanly (same voice IDs).
- `stories/pp_hunsford_proposal.md` + `build_hunsford/script.json` — second P&P scene (Chapter 34, Darcy's disastrous first proposal). Validates the pipeline on (a) a scene with Elizabeth as a speaking character for the first time, (b) inverted emotional register (fury held as ice) vs. the Reconciliation scene's tenderness. Cast reused from `cast.json` unchanged — voice consistency across scenes confirmed.
- `BENCHMARKS.md` + `pipeline/bench.py` — appended-only performance time series. Every render run records commit SHA, wall-clock render time, audio duration, real-time factor, QA pass rate, Whisper similarity, and notes. `CLAUDE.md` now requires running `pipeline.bench` on every render-touching change.
- `pipeline/qa.py` — mechanical audio QA pass (duration, peak dB, RMS dB, words-per-second, per-voice loudness consistency) + optional Whisper round-trip for faithful-rendering check. `--whisper` flag transcribes chapter MP3 via `faster-whisper` (base.en, local, int8) and diffs against concatenated script text.
- `faster-whisper` dev dep installed in venv for the Whisper round-trip.
- `_pronounce()` text-normalizer inside `tts/kokoro_backend.py`: converts name-pair slashes ("Lydia/Wickham") and `&` to spoken "and" at render time without mutating the script. Keeps the faithful-wording contract while fixing Kokoro's literal "slash" pronunciation.
- Inline dialogue-tag detection in `pipeline/render.py::_is_inline_tag` — short narrator lines sandwiched between same-speaker dialogue ("he replied," between two Darcy lines) now hug the surrounding dialogue tightly (0.4× base gap) instead of getting the full speaker-change pause.

### Changed
- `pipeline/render.py::_pause_for` now takes `nxt` and `prev_is_inline_tag` context; narrator-to-narrator continuations bumped to 1.2× base (was 0.8×) so prose sentences get breathing room; same-speaker dialogue fragments relaxed to 0.9× base.
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
