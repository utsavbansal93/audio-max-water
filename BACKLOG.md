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

### ~~`pipeline/script.py` as a real Opus subprocess call~~ (SHIPPED)

Landed as `pipeline/parse.py` + `llm/` package in the Phase 1 orchestrator. Non-Claude-Code users can now run `python -m pipeline.run --in story.md` with `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in their env; no Claude Code required.

### ~~Web UI + MCP server (Phase 2)~~ — SHIPPED as separate-invocation Phase 2

Landed as `ui/` + `pipeline/serve.py` + `pipeline/mcp_server.py`. See DECISIONS #0026 (UI stack), #0027 (backend pool), #0028 (separate invocations), #0029 (progress callback). Web UI at `http://127.0.0.1:8765` supports Anthropic + Gemini API keys; MCP server at `python -m pipeline.serve --mode mcp` exposes pipeline tools for Claude Code / Claude Desktop. The "Use my Claude app" (MCP sampling) provider option is a stub until combined-mode lands — see below.

### MCP sampling — combined UI + MCP server mode

**What.** Run the UI and the MCP server in one Python process so that, when a Claude client connects to the MCP server, the UI's parse step can use `sampling/createMessage` to route LLM generation through Claude instead of requiring an API key. This is the third LLM provider option in the UI Settings screen ("Use my Claude app"), currently stubbed with a `ConfigurationError`.

**Why deferred.** Doing it right means (a) HTTP/SSE MCP transport so FastAPI and MCP can share the asyncio event loop without fighting over stdin/stdout, (b) lifecycle management for dropped MCP client connections mid-parse, (c) documentation + Claude config templates for users to register the HTTP MCP URL. Phase 2 ships separate-invocation mode which covers the two dominant workflows (API-key-in-UI, Claude-Code-drives-tools) — sampling is the third workflow that serves a smaller audience.

**When to revisit.** When a user actually hits the stub's `ConfigurationError` and wants the feature, OR when the MCP ecosystem standardizes on HTTP/SSE transport and combined mode becomes a common pattern.

**What the work looks like.**
- Add `python -m pipeline.serve --mode both` that mounts the MCP server on an HTTP/SSE route within the same FastAPI app.
- Implement `llm/mcp_sampling_provider.py::complete()` using the server's active `RequestContext.session.create_message(...)`.
- Document Claude Desktop / Claude Code config for HTTP MCP transport.
- Handle the "no client connected" case — UI should fall back to API key automatically if a client disconnects mid-parse.

### Minor-character voice defaults

**What.** In the Phase 2 voice picker, when a character has < N lines (configurable threshold), skip the per-character picker and auto-assign from a small fallback pool. Threshold + pool are user-configurable in settings. Goal: don't make the user pick a voice for every walk-on — let the important characters get attention.

**Why deferred.** Depends on the Phase 2 UI existing. A CLI version of this isn't useful; users running `pipeline.run` already get auto-rank-1 for everyone.

**Parent.** Web UI + embedded MCP server.

### URL ingestor — "paste a link"

**What.** Let the user paste a URL on the Upload screen. If the page is reachable and its main content is extractable (non-SPA, reachable without auth, reasonably article-shaped), ingest it like any other source. Fall back to a clear error ("That page is behind auth / JavaScript-only / too short to parse") if not.

**Why deferred.** Substantially harder than file ingest: content extraction from arbitrary HTML needs heuristics like Readability, boilerplate-stripping, redirect handling, and a failure taxonomy the UI can render helpfully. The upload-a-file path covers the user's main use case today.

**What the work looks like.**
- `pipeline/ingest/url_ingestor.py` — fetches the URL via `httpx`, extracts main content via a library like `readability-lxml` or `trafilatura`, falls back to `beautifulsoup4` stripping for simple pages.
- New input type in `get_ingestor()` keyed on `http://` / `https://` prefix, not extension.
- UI: second input on `/` that accepts a URL, same `/api/upload` endpoint downstream (writes the extracted text to a synthetic `.txt` file in `build/_ui_uploads/` so the rest of the pipeline is unchanged).
- Security: follow only HTTPS redirects, bound body to a few MB, refuse non-HTML content types, don't embed user HTML in any response (already safe since we extract text).
- Clear error UX when content looks like a nav shell, paywall, or login form (very short extracted text → actionable message).

### `.mobi` ingest

**What.** Add `MobiIngestor` to `pipeline/ingest/` so users can drop Kindle `.mobi` files straight in.

**Why deferred.** No clean pure-Python MOBI parser as of April 2026 — the well-maintained path is shelling out to `KindleUnpack`. Kindle users can re-export to `.epub` via Calibre in one click, which covers the 95% case. Filed so we don't lose the requirement; will implement when a concrete user hits it.

### Auto-approve cast confidence threshold

**What.** `pipeline.run` currently auto-approves the rank-1 voice for every character. If the heuristic's top pick is only marginally better than rank-2 (score delta < X), pause and prompt the user — either interactively at the CLI or as a "please review" item in the UI.

**Why deferred.** Quality-of-life improvement; the heuristic has been right enough not to be the limiting factor. Becomes worth it when we start rendering books with 20+ characters where the heuristic makes a visibly-wrong pick on at least one.

### Emotion re-tagging pass

**What.** Optional standalone step that re-runs LLM emotion annotation on an already-parsed `script.json` — useful when you want to tune a specific chapter's dramatic peaks without re-parsing (re-parse risks faithful-wording divergence; emotion re-tag doesn't touch `line.text`).

**Why deferred.** The current parse step already emits emotion labels from book context; the only time this would help is when listening reveals a specific scene that's under- or over-emoted, and you want the LLM to reconsider without redoing the whole parse. Not a current bottleneck; file as refinement.

### LLM-driven casting (replace the tag heuristic in `pipeline/cast.py`)

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
