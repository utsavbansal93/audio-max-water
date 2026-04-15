# Audio Max Water

**Convert a written story into a narrated full-cast audiobook.** Drop a story (prose or script format) into `stories/`, run one command, get an `.m4b` with a distinct voice per character — narrator, Gatsby, Daisy, whoever. Runs locally using open-source neural TTS. No API keys, no cloud, no per-minute billing. Built and tuned primarily on Apple Silicon; see *Modifying for your system* below for Linux / NVIDIA / CPU-only setups.

---

## Quickstart (Apple Silicon Mac)

```bash
git clone https://github.com/utsavbansal93/audio-max-water
cd audio-max-water
brew install python@3.12 ffmpeg espeak-ng
python3.12 -m venv .venv
.venv/bin/pip install -e .

# 1. Put your story at stories/my_story.md
# 2. Parse it into a script (see "Source formats" below for the expected shape)
# 3. Render + QA + package + append a benchmark row:
.venv/bin/python -m pipeline.bench \
    --script build/script.json \
    --cast   cast.json \
    --build  build \
    --target "my_story ch01" \
    --notes  "first render"

# Output: out/<Title>.m4b
```

The first run downloads the Kokoro-82M weights (~300 MB) via Hugging Face.

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

Five stages, all in `pipeline/`:

1. **Parse** — Claude Opus converts the story into `script.json` (speaker, text, emotion per line). Validates byte-verbatim fidelity to the source.
2. **Cast** — maps each character to a voice. `cast.json` is authoritative and reused across chapters so voices stay consistent.
3. **Render** — for each line, looks up the voice, calls the TTS backend, caches the WAV keyed by content hash (so re-rendering unchanged lines is free).
4. **Stitch** — concatenates per-line WAVs with emotion-aware silence gaps into one chapter MP3.
5. **Package** — produces an `.m4b` with chapter markers, ready for Apple Books / `.m4b`-aware players.

See `DECISIONS.md` for the architectural reasoning behind each stage.

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
