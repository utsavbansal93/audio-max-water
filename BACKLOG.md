# Backlog

Ideas, experiments, and follow-ups that are worth doing but not now. Each entry names *why it's deferred*, not just what it is — so future sessions can re-prioritize sanely.

---

## TTS backends

### Sesame CSM (1 B, Llama-backbone)

**What.** Drop-in alternative to Chatterbox under the existing `TTSBackend` ABC. Per 2026 benchmarks, the strongest open-source engine for multi-speaker conversational speech and non-verbal cues (sighs, breath catches, tonal subtleties). Reference: https://huggingface.co/sesame/csm-1b.

**Why deferred.** Hybrid Chatterbox + LibriVox references landed well (user: "works fine") on the Gatsby reunion scene. Next-engine work is speculative until we hit a Chatterbox ceiling we can actually name. Sesame is ~3× larger than Chatterbox (1 B vs 350 M params), wants more RAM, and its setup path is less battle-tested on M3.

**When to revisit.** If we get user feedback on a future scene that Chatterbox emotion feels one-note or that multi-speaker scenes need finer tonal detail. Or when Sesame ships an MLX port (would halve the RAM cost on Apple Silicon).

**What the work looks like.** Pattern is identical to `tts/chatterbox_backend.py`: one new file (`tts/sesame_backend.py`), a line in the `tts/__init__.py` factory, a cast entry with `"backend": "sesame"`, and reference clips in `voice_samples/`. No pipeline changes — the ABC covers it.

---

## Dia (Nari Labs) — inline emotion tags

**What.** A TTS engine that accepts inline tags like `(sighs)`, `(whispers)`, `(laughs)`, `(gasps)` directly in the input text. Could map naturally to our `emotion.notes` field: if a note contains a bracketed directive, pass it through to Dia literally.

**Why deferred.** Chatterbox+LibriVox already gets us emotional range. Dia's value is mostly for *stylized* emotional moments (a character gasps mid-sentence) that our current pipeline can't express except through line splitting.

**When to revisit.** When we hit a scene where the *style* of emotion matters more than the *intensity* — a character breaking down mid-line, an audible laugh, whispered asides. Austen doesn't need this; modern fiction might.

---

## Pipeline ergonomics

### Supervisor/worker pattern for bulk rendering

**What.** One long-lived Python process loads each backend (Kokoro, Chatterbox, Whisper) exactly once at startup and exposes a request queue; the existing `pipeline.render`, `pipeline.qa`, `pipeline.bench` CLIs become thin clients that connect to the supervisor over a Unix socket. N chapters rendered in one supervisor lifetime = 1× model load cost instead of N×. Concurrency is budgeted explicitly at the supervisor ("one Chatterbox slot, three Kokoro slots, one Whisper slot") with graceful back-pressure when the budget is full.

**Project-specific requirement (non-negotiable for this backlog entry).** *The supervisor must log per-request memory stats* to a rotating file: peak RSS during synthesis, RSS before/after each request, queue depth, concurrent-request count, backend, request duration. One line of JSON per request so the log is easy to `jq` / load into pandas. This instrumentation is the prerequisite for the companion entry below.

**Why deferred.** Current workflow is one scene at a time for listening + iterating — throughput isn't bottlenecked yet. The supervisor earns its complexity when rendering multi-chapter works or serving concurrent submissions from a future web UI.

**When to revisit.** First full-novel render; or when someone wants to queue multiple stories; or when startup latency (model loading per invocation) becomes a bottleneck versus actual synthesis time.

**What the work looks like.** `pipeline/supervisor.py` + a JSON-over-Unix-domain-socket protocol, thin-client refactor of the existing CLIs, logging infrastructure, plus a start/stop/status utility. Moderately-sized — a few sessions of work.

### Review memory-usage logs; relax the concurrency rule empirically

**What.** Once the supervisor (entry above) has accumulated logged per-request RSS data from real renders across diverse stories, analyze the distribution per backend. Questions to answer:
- What's the actual 95th-percentile peak RSS for Chatterbox across our scripts? (Current conservative estimate: 2.5 GB. If the real number is 1.8 GB, we have headroom to allow concurrent Kokoro + Chatterbox.)
- Does peak RSS correlate with text length, intensity, or pace? If yes, the concurrency rule can be request-size-aware.
- Are there line patterns (long sentences, certain intensity ranges) that reliably cause RSS spikes? Flag them for mitigation.

The output is a revision to `CLAUDE.md`'s per-backend budget and/or to the watchdog thresholds in `pipeline/_memory.py`. Goal: let the system tell us empirically when we can safely relax constraints, rather than guessing.

**Why deferred.** Depends entirely on the supervisor entry existing *and* having run enough to produce a meaningful dataset (probably weeks of regular use, not days).

**Parent.** Supervisor/worker pattern (above).

### LLM-driven casting (replace the tag heuristic in `pipeline/cast.py`)

**What.** Opus reads the script's `characters` and `book_context` and picks a voice with reasoning, rather than our trait-keyword scoring in `_score()`. Output would include per-character justification for DECISIONS logging.

**Why deferred.** Heuristic has not produced a bad pick that a swap couldn't fix. Every cast the user has approved after auditions has been `rank 1` or `rank 2` — no systematic miss that LLM reasoning would fix. Cost: context tokens per casting run.

**When to revisit.** If we build many more scenes and start seeing the heuristic systematically miss on certain character archetypes, or when Chatterbox/Sesame voice libraries grow beyond what simple tag-scoring can navigate.

### `pipeline/script.py` as a real Opus subprocess call

**What.** Today the parse step is "me-in-Claude-Code-authoring script.json by hand." Would be nice to call Opus programmatically so a non-Claude-Code user can run the full pipeline without me in the loop.

**Why deferred.** The user hasn't wanted to run the pipeline outside Claude Code yet. When they do, this becomes the blocker.

### Web UI (Phase 2 from the original plan)

**What.** Tiny FastAPI + HTML front door for uploading stories, approving cast samples in-browser, downloading finished `.m4b`.

**Why deferred.** CLI works, user hasn't asked for it since the original plan. Becomes worth it if a non-technical user of this tool is on the horizon, or if managing many stories simultaneously gets tedious.

---

## Cast / voice library

### Expand Chatterbox reference library to the P&P cast

**What.** Same LibriVox-sourcing pattern applied to Karen Savage's (or another) solo reading of P&P — extract refs for Darcy, Elizabeth, Mr. Bennet, Mrs. Bennet, Lady Catherine, etc. Enables running P&P scenes through Chatterbox if a scene needs more emotion than Kokoro delivers.

**Why deferred.** The Austen Kokoro voices work for the current P&P scenes. Only worth doing when we're rendering an Austen scene where Kokoro falls flat (e.g., Mrs. Bennet at her most hysterical, Lady Catherine at her most imperious — characters whose comedy lives in vocal modulation).

### SOURCES.md → a proper catalogue

**What.** Today `voice_samples/SOURCES.md` lists two clips. If the library grows past ~10, it wants per-clip metadata in a parseable format (JSON/YAML) that can feed the audition UI.

**Why deferred.** Two clips is not a catalogue.

---

## QA / eval

### Multimodal LLM listener (Gemini 2.5 Pro with audio input)

**What.** Pass the rendered m4b to Gemini and ask "does this character sound angry on line 14? Does the narrator pace feel natural?" — an actual AI ear, not a transcription check.

**Why deferred.** Requires API key + network + per-request cost; current Whisper round-trip + mechanical QA catches the failure modes we've actually seen. The remaining failure mode ("does it sound emotionally right") is exactly what the human ear is good at — promoting a machine to judge it is speculative.

**When to revisit.** When bulk rendering (entire novels) makes per-chapter human listening impractical.

### Automatic QA-threshold calibration

**What.** QA flagged two Hunsford lines at the threshold boundaries (peak −1.0 dB, pacing below 1.3 w/s on a 3-word sentence). Thresholds are hand-picked from audiobook industry lore; they should adapt to the distribution of lines we actually render.

**Why deferred.** Two false positives in a month of renders is signal, not noise. When the false-positive rate climbs, calibrate.
