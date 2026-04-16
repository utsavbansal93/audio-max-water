# Audio Max Water

**Convert a written story into a narrated full-cast audiobook.** Drop a book (plain text, Markdown, Word, EPUB, or PDF) into the pipeline, run one command, get an `.m4b` — or an Audio-EPUB3 with synced text + audio — with a distinct voice per character. Runs locally using open-source neural TTS. Bring your own Anthropic or Gemini API key for the one LLM-driven step (parsing the source into a structured script); everything else is deterministic and offline. Built and tuned primarily on Apple Silicon; see *Modifying for your system* below for Linux / NVIDIA / CPU-only setups.

---

## Quickstart — one command, any supported input (Apple Silicon Mac)

```bash
git clone https://github.com/utsavbansal93/audio-max-water
cd audio-max-water
brew install python@3.12 ffmpeg espeak-ng
python3.12 -m venv .venv
.venv/bin/pip install -e '.[ingest,llm]'

# One LLM call is needed to parse the source into a structured script.
# Export ONE of these — pick your provider:
export ANTHROPIC_API_KEY=sk-ant-...        # Anthropic (default)
# export GEMINI_API_KEY=AI...              # or Gemini (add --provider gemini)

.venv/bin/python -m pipeline.run \
    --in  stories/pp_final_reconciliation.md \
    --out out/ \
    --format m4b               # or: epub3  (text+audio synced ebook)
# Optional:
#   --cover  path/to/cover.jpg # embed cover art in the output
#   --backend kokoro           # override config.yaml TTS backend
#   --provider gemini          # use Gemini instead of Anthropic
#   --no-whisper               # skip Whisper round-trip QA (faster)

# Output: out/<Title>.m4b  (or <Title>.epub for audio-EPUB3)
# Logs:   build/<input-stem>/run.log  (full traceback on any failure)
```

The first run downloads the Kokoro-82M weights (~300 MB) via Hugging Face.

**Supported inputs.** `.txt`, `.md`, `.docx`, `.epub`, `.pdf`. For Kindle `.mobi`, export to `.epub` via Calibre first (one click).

**Output formats.**
- **`.m4b`** — standard audiobook with chapter markers. Plays in Apple Books, Audiobookshelf, VLC, Plex, any `.m4b`-aware player. Optional cover art embedded via ffmpeg.
- **`.epub` (Audio-EPUB3)** — EPUB3 package with [SMIL Media Overlays](https://www.w3.org/TR/epub-33/#sec-media-overlays): text + synchronized audio, so Thorium / Apple Books / VoiceDream highlight each paragraph as its audio plays. Graceful degradation on non-SMIL readers (shows as a clean text ebook with embedded audio tracks).

---

## Try before you clone

Three short rendered samples live in [`examples/`](examples/). Drop any of these into Apple Books or any `.m4b` player to hear what the pipeline produces with the current defaults:

- **`pp_reconciliation_sample.m4b`** (82 s) — Jane Austen's *Pride and Prejudice*, Chapter 58. All-Kokoro, British cast. Demonstrates the default zero-touch path.
- **`pp_hunsford_sample.m4b`** (72 s) — Chapter 34 of the same book. Different scene, same voices — shows cross-scene voice consistency via `cast.json`.
- **`gatsby_west_egg_sample.m4b`** (125 s) — Fitzgerald's *Great Gatsby*, Chapter 5. **Hybrid engine**: Kokoro narrator + Chatterbox characters voice-cloned from a [LibriVox Dramatic Reading](https://librivox.org/the-great-gatsby-version-5-by-f-scott-fitzgerald/). See [`examples/README.md`](examples/README.md) for what to listen for.

---

## Source formats

Two ways to write a story. Both pass the same faithful-wording contract (see `DECISIONS.md`).

**Prose** — for translating existing published work:

```
"If you will thank me," he replied, "let it be for yourself alone…"
```

Claude Opus parses dialogue from context, assigns speakers, and infers emotion from a `book_context` block you supply.

**Script** — recommended for original writing:

```
Gatsby: (In a hollow, automatic voice) Five years next November.
Daisy:  (Her voice as matter-of-fact as it could ever be) We haven't met for many years.
```

Speaker labels (`Gatsby:`, `Daisy:`) are stripped by the validator. Parenthetical stage directions flow straight into `emotion.notes` in `script.json` — you direct the actor, no guesswork.

---

## How it works

Six stages, all in `pipeline/`, chained by `pipeline/run.py`:

1. **Ingest** — `pipeline/ingest/` reads the source file (`.txt`, `.md`, `.docx`, `.epub`, `.pdf`) and normalizes it into a canonical markdown representation. One ingestor per format; all share an `Ingestor` ABC + `RawStory` intermediate. Deterministic, offline.
2. **Parse** — `pipeline/parse.py` sends the canonical source to your LLM provider (Anthropic or Gemini, via `llm/`) with `prompts/parse_story.md` as the system prompt. Result is `script.json` — speaker, text, and emotion per line. Validates byte-verbatim fidelity via the existing faithful-wording validator; retries once on divergence with targeted context.
3. **Cast** — maps each character to a voice. `cast.json` is authoritative and reused across chapters so voices stay consistent. `pipeline.run` auto-approves rank-1 per character; override manually via `pipeline.cast --swap` if you want to change voices after listening.
4. **Render** — for each line, looks up the voice, calls the TTS backend, caches the WAV keyed by content hash (so re-rendering unchanged lines is free).
5. **QA** — `pipeline/qa.py` runs signal-level checks (duration, peak, RMS, pacing, per-voice loudness consistency) + optional Whisper round-trip (gracefully skipped when `faster-whisper` isn't installed).
6. **Package** — `pipeline/package.py` dispatches to `.m4b` (ffmpeg + chapter markers + optional attached_pic cover) or audio-EPUB3 (`pipeline/epub3.py`, SMIL Media Overlays + per-line timing).

See `DECISIONS.md` (entries #0021–#0025 cover the Phase 1 orchestrator refactor) for the architectural reasoning behind each stage.

---

## Web UI (Phase 2)

Start the local web UI instead of (or alongside) the CLI:

```bash
.venv/bin/pip install -e '.[ui]'
.venv/bin/python -m pipeline.serve --mode ui        # opens http://127.0.0.1:8765
# or, for Claude Code integration via MCP (stdio):
.venv/bin/python -m pipeline.serve --mode mcp
```

The UI's five-screen flow mirrors the CLI: **Upload → Voices → Options → Rendering → Done**. Settings lives at `/settings` (provider + API key + defaults). History lives at `/history` — every job is persisted to `build/_jobs/<job_id>.json` so it survives server restarts. Failed or interrupted jobs get a **Resume** action that restarts from the last completed stage (parse / cast / render are all individually cacheable). Progress streams via Server-Sent Events — each pipeline stage shows as a pill (pending / active / done / error) with a live sub-progress bar during render.

EPUB inputs skip front-matter (cover, title page, copyright, table of contents, colophon, index) and start from the first piece of real content — preface, dedication, foreword, introduction, prologue, or Chapter 1. A one-line warning in the log lists what was skipped.

---

## Advanced: driving individual stages

The orchestrator is a convenience; the underlying modules are still separately invokable for surgical work.

```bash
# Parse only — useful if you want to hand-edit script.json before rendering
.venv/bin/python -m pipeline.parse --in stories/my_story.md --build build_my_story

# Cast with interactive auditions (old flow)
.venv/bin/python -m pipeline.cast --propose                # top-3 voices per character + audition samples
.venv/bin/python -m pipeline.cast --swap Darcy 2           # promote rank-2 for Darcy
.venv/bin/python -m pipeline.cast --approve                # freeze cast.json

# Render + QA + benchmark row (historical flow; still works)
.venv/bin/python -m pipeline.bench --target "my_story ch01" --notes "baseline"

# Package an existing build into another format without re-rendering
.venv/bin/python -m pipeline.package --build build_my_story --format epub3 --out out/
```

---

## Casting voices

```bash
.venv/bin/python -m pipeline.cast --propose              # top-3 voices per character + audition samples
.venv/bin/python -m pipeline.cast --swap Darcy 2         # promote rank-2 proposal for Darcy
.venv/bin/python -m pipeline.cast --approve              # freeze cast.json
```

Audition samples end up in `samples/cast/<character>/*.wav`. `cast.json` is the source of truth for `character → voice_id` — don't regenerate it implicitly.

For multi-book projects, use per-book cast files (`cast_gatsby.json`, `cast_pp.json`, etc.) and pass them via `--cast`. Voice drift across books is expected and correct.

---

## Swapping TTS engines

Edit `config.yaml`:

```yaml
backend: mlx-kokoro    # default on Apple Silicon
```

Supported backends:

| Backend | Expressiveness | Speed (M3) | Setup |
|---|---|---|---|
| **mlx-kokoro** | Limited (no emotion input) | RTF ~0.15 | None beyond `pip install -e .` |
| **kokoro** (torch) | Same as mlx-kokoro | RTF ~0.21 | Works on any platform (CPU/CUDA/MPS) |
| **chatterbox** | Explicit emotion slider, voice cloning | Slower, larger model | `pip install chatterbox-tts` + reference clip per voice |

Both Kokoro backends share voice IDs and `cast.json` files. Chatterbox uses reference clips from `voice_samples/`.

---

## Modifying for your system

This project was built and tuned on an M3 MacBook Air. These are the parts that may need changing on other hardware.

### Linux or other Unix

- Replace `brew install …` with your distro's package manager (`apt install python3.12 ffmpeg espeak-ng`, `pacman -S …`, etc.).
- The code already uses `shutil.which("ffmpeg")` / `shutil.which("ffprobe")`, so as long as they're on `$PATH`, nothing else changes.
- Python 3.12 via `pyenv` or your distro.
- You cannot use the `mlx-kokoro` backend (Apple-Silicon-only via MLX). Set `backend: kokoro` in `config.yaml` — same Kokoro weights, torch runtime, portable everywhere.

### NVIDIA / CUDA

- Use `backend: kokoro` (not `mlx-kokoro`).
- Kokoro backend default device is determined by torch; it will pick CUDA if available. If you want to force it, patch `tts/kokoro_backend.py` to pass `device="cuda"` to `KPipeline`.
- Chatterbox: pass `device="cuda"` in its `from_pretrained()` call.
- Expect RTF on the order of the M3 numbers or better.

### CPU-only / low-RAM

- `backend: kokoro` works on CPU with the 82M-param model — slow but functional.
- Avoid Chatterbox on CPU (0.5B+ params, ~10× slower than on GPU).
- Drop `faster-whisper` to `tiny.en` or skip `--whisper` entirely in the QA pass to save memory.

### Windows

- Most Python deps work fine. `espeak-ng` is trickier — install from the [espeak-ng releases](https://github.com/espeak-ng/espeak-ng/releases) and ensure `espeak-ng.exe` is on `%PATH%`.
- `afplay` (Mac-only) appears in a few docs for playback — use the OS's default player instead.

### What's Mac-specific vs cross-platform

| Mac-specific | Cross-platform |
|---|---|
| `mlx-kokoro` backend (MLX is Apple-Silicon-only) | Everything in `pipeline/` |
| `/opt/homebrew/` paths in older commits (now `shutil.which`) | `kokoro` (torch) and `chatterbox` backends |
| Playback examples using `afplay` | `ffmpeg`, `faster-whisper`, `espeak-ng` |

---

## Troubleshooting

- **Kokoro model won't download** — set `HF_HOME` to a writable path, or `HF_TOKEN` if you hit anonymous-rate-limit warnings (they usually don't block; just slow the first download).
- **`espeak-ng not found`** — Kokoro falls back to it for out-of-vocabulary words. Install via your package manager.
- **ffmpeg chapter markers missing in Apple Books** — re-import the `.m4b`; Books caches aggressively.
- **Voices drift across chapters** — `cast.json` was regenerated. It's the source of truth; recover from git and render again.
- **A line sounds wrong** — rerunning `pipeline.render` only re-synthesizes lines whose content hash changed, so edit `script.json` for that line and re-render; other lines reuse their cached WAVs.
- **"MissingDependency: X needs Y which is not installed"** — the message includes the exact `pip install` command. Run it and retry. Required deps (ingest for the format you used, LLM SDK for parse) block the run; optional ones (Whisper QA) are auto-skipped with a warning and the render still ships.
- **"ANTHROPIC_API_KEY not set"** — `pipeline.run` needs an LLM key for the parse step only. Export `ANTHROPIC_API_KEY` or switch to Gemini with `--provider gemini` + `GEMINI_API_KEY`. Everything after parse is LLM-free.
- **Everything else** — check `build/<input-stem>/run.log` for the full traceback. The console shows a one-line summary; the file has the stack.

---

## Project documents

- `CLAUDE.md` — rules for AI assistants (Claude Code, etc.) working in this repo: logging discipline, faithful-wording contract, voice-consistency contract, backend-swappability contract. If you're using an AI assistant for changes here, point it at this file.
- `DECISIONS.md` — numbered architectural decisions with context/options/consequences for each non-obvious choice.
- `STORY.md` — narrative build log. The "why" behind the "what", written as it happened. Retrospective-ready.
- `CHANGELOG.md` — dated entries, Keep-a-Changelog format.
- `BENCHMARKS.md` — render-time / audio-duration / RTF / QA pass-rate / Whisper similarity across every iteration.

---

## License

MIT. See `LICENSE` if present. Source reference clips (from LibriVox or similar) are used under their own public-domain / CC attribution; see `voice_samples/SOURCES.md` once added.
