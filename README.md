# Audio Max Water — Story → Full-Cast Audiobook

Turn Claude-written stories into narrated `.m4b` audiobooks with a distinct voice per character. Free tooling, runs locally on Apple Silicon.

## What it does

1. **Parses** a story (markdown / plain text) with Claude Opus into a structured script: narrator + characters, each line tagged with emotion grounded in book-level context.
2. **Casts** a voice per character from the active TTS backend's library; you approve samples before commit.
3. **Renders** each line with the cast voice + emotion, preserves per-line audio for surgical re-renders.
4. **Packages** the chapter(s) as `.m4b` with chapter markers, ready for Apple Books.

Wording is kept byte-verbatim from the source. Voice-per-character is locked in `cast.json` and reused across chapters.

## Requirements

- macOS on Apple Silicon (tested on M3 16 GB)
- Python 3.12 (`brew install python@3.12`)
- `ffmpeg` (`brew install ffmpeg`)
- Claude Code CLI (for the Opus parsing + casting steps)

## Install

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

Install extra engines only when you want to swap to them:

```bash
.venv/bin/pip install chatterbox-tts     # emotion-first
.venv/bin/pip install TTS                # Coqui XTTS v2 (voice cloning)
```

## Run (CLI, Phase 1)

```bash
# 1. Drop your story in stories/ and run the pipeline
.venv/bin/python -m pipeline.script stories/my_story.md      # → build/script.json
.venv/bin/python -m pipeline.cast  --propose                 # → cast.json + samples/
#    approve with: python -m pipeline.cast --approve
#    or swap:      python -m pipeline.cast --swap Elena 2
.venv/bin/python -m pipeline.render build/script.json        # → build/ch*/lines/*.wav
.venv/bin/python -m pipeline.package                         # → out/<title>.m4b
```

Or the one-shot convenience:

```bash
make audiobook STORY=stories/my_story.md
```

## Quality-check & benchmarks

```bash
.venv/bin/python -m pipeline.qa --whisper                              # mech QA + Whisper round-trip
.venv/bin/python -m pipeline.bench --target "<label>" --notes "<what changed>"
```

`pipeline.qa` flags duration/peak/RMS/pacing anomalies and (with `--whisper`) transcribes the chapter MP3 via `faster-whisper` and diffs against the script — catches mispronunciations and dropped words.

`pipeline.bench` renders + runs QA + appends a row to `BENCHMARKS.md` (commit SHA, wall-clock, audio duration, RTF, QA pass rate, Whisper similarity, notes). Run this on every tune-or-experiment so the perf time series stays intact — see `CLAUDE.md`.

## Run (web UI, Phase 2)

Not yet. Layered on after the CLI is solid.

```bash
.venv/bin/uvicorn ui.app:app --reload    # localhost:8000
```

## Swapping TTS backends

Edit `config.yaml`:

```yaml
backend: kokoro    # or: chatterbox, xtts
```

No pipeline code changes. Backends that need reference audio (Chatterbox, XTTS) read clips from `voice_samples/<character>.wav`.

## Engine comparison (default: Kokoro)

| Engine | Voices | Emotion | Notes |
|---|---|---|---|
| **Kokoro** (default) | 50+ presets | Implicit (punctuation) | Deterministic, fast, zero-touch casting |
| Chatterbox | Voice cloning | Explicit slider | Best emotional range, needs reference clips |
| XTTS v2 | Voice cloning | Reference-matched | Coqui unmaintained; works but aging |

See `DECISIONS.md` for the full trade-off analysis and `samples/COMPARISON.md` for the P&P test.

## Project docs

- [`CHANGELOG.md`](CHANGELOG.md) — what changed, when
- [`DECISIONS.md`](DECISIONS.md) — non-obvious choices and their rationale
- [`STORY.md`](STORY.md) — narrative of how this got built; retrospective material
- [`CLAUDE.md`](CLAUDE.md) — rules for Claude Code sessions in this repo

## Troubleshooting

- **Kokoro model won't download**: set `HF_HOME` to a writable path.
- **ffmpeg chapter markers missing in Apple Books**: re-import; Books caches aggressively.
- **Voice drift across chapters**: confirm `cast.json` wasn't regenerated. It's the source of truth.
