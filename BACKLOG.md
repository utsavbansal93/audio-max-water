# Backlog

Ideas, experiments, and follow-ups that are worth doing but not now. Each entry names *why it's deferred*, not just what it is — so future sessions can re-prioritize sanely.

---

## P0 — blocking quality

P0 items ship before any other backlog work. They represent quality failures the user has hit in a real render and cannot be worked around without orchestrator intervention.

### Auto voice-sample search matched to character personality

**What.** When the cast-diversity check in CLAUDE.md trips (≥2 main characters of the same gender collapsing onto one Kokoro preset), the pipeline should automatically:
1. Search an indexed library of public-domain reference clips (LibriVox dramatic readings is the seed source — ~thousands of multi-cast productions with per-character actors) for candidates matching the affected characters' personality descriptors.
2. Score each candidate by **embedding-based personality match** — a sentence-transformer cosine between the `character.personality` string and each clip's personality tags (pre-computed at index time from LibriVox cast notes and/or a small LLM pass over the source book's character description). Efficient but not robotic: not a keyword/regex match that over-weights single words.
3. For each affected character, produce a `{"voice": "<stem>", "backend": "chatterbox"}` suggestion in `cast.json`, download+normalize the top clip into `voice_samples/`, and append to `voice_samples/SOURCES.md`.
4. Surface suggestions to the user (UI prompt or CLI audition) before committing.

**Why deferred.** Meaningful pipeline work across three layers — indexing (download + Whisper-timestamp + tag every LibriVox multicast), embedding (sentence-transformer + vector store), and UX (audition + approve). The Hyperthief render of 2026-04-17 did the whole thing by hand as proof-of-concept (5 clips, manual LibriVox selection, manual `cast_hyperthief.json`) so the cost/value is understood.

**When to revisit.** Next render that trips the cast-diversity check — at that point the second-time-manual work argues for automation. See also the existing backlog entry "Voice dataset matching via jim-schwoebel/voice_datasets" below as a source-expansion direction once the core auto-search loop lands.

**Dependencies.** The cast-diversity check from CLAUDE.md must fire as a hard error (not a soft warning), which argues for also shipping the "Voice-uniqueness invariant for main characters" entry under `## Cast / voice library` below around the same time.

---

## TTS backends

**Engine taxonomy (so the entries below land in context).** All TTS engines we use or might use are *neural*; the meaningful axis is **non-autoregressive vs autoregressive LLM-based**. Non-autoregressive engines (Kokoro / MLX-Kokoro, StyleTTS2-style, 82 M params) accept text + speed only — there is no emotion input, and emotional shading is a side-effect of punctuation and pace. Autoregressive LLM-based engines (Chatterbox uses a Llama-0.5 B backbone) predict audio tokens conditioned on a reference clip and an exaggeration / prompt slider, which is what makes "true surprised", "vulnerable", "weighty" delivery possible at all. **Dia** (below) is autoregressive LLM-based and a direct Chatterbox alternative. **Sesame CSM** is architecturally different — see its entry.

**What Dia would substitute.** Dia replaces **Chatterbox** in the hybrid stack — same `TTSBackend` ABC slot, same reference-clip-for-identity paradigm, but adds inline emotion tags. Sesame is NOT a drop-in for Chatterbox — see its entry for the correct framing.

**The non-verbal-sound capability ladder** (sighs, sobs, gasps, audible laughs):
- *Kokoro* — none. Reads `(sigh)` as the word "sigh".
- *Chatterbox* — partial: word delivery can be made breathy / intense / vulnerable via the `exaggeration` slider plus an emotionally matched reference clip. But it cannot produce a discrete audible sigh / sob / gasp as a sound event.
- *Sesame CSM* — not a voice-cloning engine; see entry.
- *Dia* — the only one of the four that produces **discrete non-verbal vocalizations on demand** via inline `(sighs)` / `(laughs)` / `(gasps)` text tags. Also solves full emotional register switching via inline directives.

### Sesame CSM (1 B, Llama-backbone) ⚠️ very low priority

**What.** A *contextual* TTS model — not a voice-cloning engine. Reference: https://huggingface.co/sesame/csm-1b. CSM is explicitly "not fine-tuned on specific voices" and not designed for zero-shot voice cloning from an arbitrary reference clip. It generates consistent speaker voices when given multi-turn conversational audio context (prior dialogue turns from the same speakers), which is a different paradigm entirely from Chatterbox's reference-clip conditioning. Hardware: CUDA or CPU, 1 B params, no MLX/MPS support.

**What it actually gets us.** Not a Chatterbox replacement. Its value is multi-speaker conversational coherence — if we ever build a system where multiple speakers take turns and each needs to stay tonally consistent *relative to what they just said*, Sesame's context window is the right tool. This does not apply to our current pipeline where each line is rendered independently and stitched.

**Why deferred.** Sesame does not fill any gap we currently have. It cannot slot into the `TTSBackend` ABC as a Chatterbox replacement because it requires conversational context rather than a reference clip. Its use case only becomes relevant if we build a dialogue-aware rendering loop where prior audio turns are fed back as context.

**When to revisit.** Only when a concrete conversational rendering use case is identified — e.g. a back-and-forth dialogue where each character's next line needs to be tonally conditioned on their previous output. Do not revisit for general emotional range or voice cloning needs; Dia and emotion-keyed clips cover those.

---

## Dia (Nari Labs) — inline emotion tags

**What.** An autoregressive transformer TTS engine that accepts inline tags like `(sighs)`, `(whispers)`, `(laughs)`, `(gasps)`, `(sobbing)` directly in the input text. Voice identity is set by a reference clip (same paradigm as Chatterbox). Slots into Chatterbox's role under the `TTSBackend` ABC; LibriVox reference clips remain the audio source. Reference: https://github.com/nari-labs/dia.

**Hardware.** ~4.4 GB in bfloat16 (benchmarked on RTX 4090). CUDA-only as of April 2026 — CPU support is explicitly listed as "to be added soon" in the repo; Docker ARM/MacOS support is a TODO. At 4.4 GB bfloat16, it fits within the 16 GB M3 budget once MPS support lands.

**What it gets us beyond Chatterbox.** Two things Chatterbox cannot do: (1) discrete non-verbal vocalizations on demand — an actual audible sob, gasp, or laugh as a sound event, not just intensity-colored word delivery; (2) full emotional register switching — `(joyful)`, `(sobbing)`, `(hysterical)` as inline directives collapse the multi-clip problem back to one reference clip per character. Chatterbox's exaggeration slider modulates intensity within a register; Dia shifts the register itself. This is the engine for characters who need genuine emotional range.

**Why deferred.** CUDA-only right now — cannot run locally on M3. The medium-term workaround is emotion-keyed reference clips (see Cast / voice library below) which solve the same range problem with Chatterbox today. Dia becomes the cleaner solution once CPU or MPS support ships.

**When to revisit.** When nari-labs ships CPU or MPS support — watch https://github.com/nari-labs/dia for the release. At that point, integration is: one new `tts/dia_backend.py`, a factory line in `tts/__init__.py`, and a small extension to the faithful-wording validator to strip `(...)` directives from the reconstructed text path while keeping `script.json::text` byte-verbatim.

---

## Render modes

### Single-actor mode ("acting-oriented" build)

**What.** A render mode where the entire book is performed by one voice actor — but the actor dramatically differentiates every character through performance parameters, not through distinct voice identities. Think solo stage performer playing a full cast: same throat, entirely different presences.

This is distinct from the current "full cast" paradigm in a meaningful way:
- **Full cast (current default):** one distinct voice ID per character → identity differentiation. The acting is secondary.
- **Single actor (this mode):** one voice ID for all characters → differentiation via acting profile per character. Pace, energy, exaggeration, pitch contour, pause cadence, and emotional register carry the whole characterization burden.

**UI.** On the Options screen, a new "Performance mode" toggle: **Full cast** (default) vs **Solo performance**. In solo mode, the voice picker collapses to a single "Actor" selection (one reference clip + backend). Character acting profiles are either auto-generated by the LLM or tuned in a per-character sheet below the actor picker.

**Implementation surface.**
- `config.yaml`: `output.render_mode: full_cast | single_actor`
- In `single_actor` mode, `pipeline/cast.py` skips per-character voice assignment entirely. Instead it writes a `cast.json` with one `_actor` entry (voice + backend) and per-character `acting_profile` objects:
  ```json
  "_actor": { "voice": "suzy_ref", "backend": "chatterbox" },
  "characters": {
    "FM": { "speed_mult": 1.1, "exaggeration": 0.45, "pause_mult": 0.8, "energy": "bright" },
    "Rig": { "speed_mult": 0.88, "exaggeration": 0.65, "pause_mult": 1.3, "energy": "gruff" },
    "Narrator": { "speed_mult": 0.92, "exaggeration": 0.30, "pause_mult": 1.1, "energy": "measured" }
  }
  ```
- `pipeline/render.py` in single-actor mode: all lines go through the same backend + reference clip, but per-line render parameters (speed, exaggeration, pause durations) come from the character's acting profile rather than from the line's cast entry.
- LLM parse step optionally emits `character.archetype` (e.g. "nervous+eager", "gruff+laconic", "imperious+brittle") that the casting step translates into acting parameter heuristics. Same `book_context` → `character` pipeline, different output schema.
- The voice-uniqueness invariant in `pipeline/validate.py` is explicitly skipped in `single_actor` mode — voice sharing is the point.

**The research angle — the real reason this is worth building.** Discovering what parameter combinations make characters feel distinct is directly applicable to multi-actor mode. If `exaggeration=0.65 + speed=0.88 + slow pauses` reliably produces a character that doesn't get confused with `exaggeration=0.45 + speed=1.1 + fast pauses`, those findings inform how we should be configuring per-character Chatterbox calls even when distinct reference clips are in play. Single-actor mode is effectively a controlled experiment: one confound removed (voice identity), everything measurable is the acting signal. The accumulated acting profiles from each book render can be analyzed and fed back into per-actor guidance.

**Constraints for differentiation to actually work.**
- At least 4 distinct parameters must differ meaningfully between any two main characters (same-speaker confusion is the failure mode).
- Auto-generated profiles need an explicit conflict-check: if two main characters have similar archetypes (both "calm+reserved"), force at least one parameter to a distinct extreme.
- Dia's inline `(whispers)`, `(gruff)`, `(joyful)` tags are a natural fit here — when Dia-on-MPS ships, this mode becomes dramatically more capable.

**Why deferred.** The acting profile → parameter mapping needs empirical grounding: which exaggeration values correspond to which character feels, what pace delta is perceptible vs inaudible, how far apart two characters need to be on the parameter space to avoid confusion. That calibration requires building and listening to actual single-actor renders. There's no prior art in this pipeline to derive from.

**When to revisit.** When a user explicitly selects "Solo performance" in the UI (the mode should exist at the config level before the UI picker exists — CLI first); OR when Dia ships (its native tag system makes the parameter mapping trivially richer); OR when a story arrives where the user simply wants one voice and doesn't have reference clips for five characters.

**Dependencies.** `output.render_mode` config toggle (trivial); acting profile schema in `cast.json` (small schema extension); Dia backend (optional but high-leverage); emotion-keyed reference clips entry (for the multi-actor feedback loop payoff).

---

## Pipeline ergonomics

### Configurable branding intro tag

**What.** A configurable intro line (e.g. "This audiobook presented to you by UB Audiobooks.") prepended as the first spoken narrator line of chapter 1. Config via `config.yaml: output.intro_tag` (string; default empty = off). Implementation surface: `pipeline/parse.py::parse_to_disk`, immediately after the LLM/cache returns — prepend the tag as both an H1 line in `source.md` and as `chapter[0].lines[0]` in `script.json`, so the faithful-wording validator's H1-strip-but-keep-text path makes the reconstruction round-trip cleanly.

**Why deferred.** Demonstrated end-to-end on Hyperthief (2026-04-17) by hand-editing `source.md` + `script.json`; works. The config wiring is simple but not on the current hot path. Only earns its complexity when we start running many books through the orchestrator and want consistent branding without orchestrator intervention every time.

**When to revisit.** When the user's audiobook output starts being shared with others (as distinct from personal listening), OR when a second brand tag is requested (plural => config).

### Optimal hardware resource usage — a strategy, not just a policy

**What.** A first-class notion in the pipeline of "how do we get the best wall-clock + quality trade-off out of the hardware available right now?" Not just a memory-budget rule, but an active strategy that:

1. **Probes hardware on startup** — detects CPU count (perf + efficiency cores), RAM, whether a discrete GPU is present, whether CUDA/MPS/ROCm is usable, whether the Neural Engine is engageable (via CoreML models). Writes a one-time `hardware.json` to the build dir.
2. **Picks a rendering strategy per hardware class.** Examples:
   - *M-series fanless (MBA)*: one backend process per engine, no multi-process, thermal-aware throttling — prefer batching inside the process, accept sequential per-line.
   - *M-series active-cooled (MBP, Studio)*: one or two Chatterbox processes safe, can overlap Kokoro + Chatterbox in separate processes because memory is abundant.
   - *x86 + NVIDIA*: many-process parallelism safe, pin each process to its own GPU if multi-GPU, use CUDA streams for intra-process concurrency, ignore the fanless-specific throttling rules.
   - *CPU-only Linux server*: all-Kokoro-only, forget Chatterbox, high-process-count is OK.
3. **Logs telemetry per render** (peak RSS, per-line wall time, MPS queue depth if accessible, CPU %, GPU util via `mps` or `nvidia-smi`) so future strategy picks are data-driven.
4. **Owns the concurrency knobs.** Today the concurrency knobs are scattered — `pipeline/_memory.py::require_free` is a blocking check, CLAUDE.md has memory discipline rules, some modules use `ThreadPoolExecutor`, no one place enforces "how many concurrent Chatterbox inferences across the whole process tree". Consolidate.

**Whose job is it?** New module: `pipeline/resource_strategy.py`. Exposes `get_strategy() -> RenderStrategy` which the orchestrator asks before picking concurrency. Lives next to `pipeline/_memory.py` as a thin layer above it. Eventually absorbs `_memory.py`'s logic. The Supervisor entry below is a peer — the Supervisor is the *service* that executes concurrent work; the resource strategy is the *policy* that decides how much concurrent work is safe on *this* machine.

**Why deferred.** Hyperthief render of 2026-04-17 revealed this gap the hard way: the orchestrator (Claude acting by hand) spawned a Chatterbox worker process to parallelize, observed ~1.47× speedup over an 84-second warm-up window, then over a 12-minute sustained window discovered it was actually a 38% regression because Apple's MPS is single-queue. Had a resource-strategy module existed, it would have refused the worker spawn on M3 for exactly that reason. Knowing the hardware's characteristics matters more than the work's characteristics once you have meaningful work.

**When to revisit.** (a) When rendering across more than one hardware class (user gets a desktop, or project ships to others). (b) When measurement/telemetry is needed for anything (already a Supervisor dependency — pair them). (c) When any new backend ships that has different scheduling properties than Kokoro/Chatterbox (Dia via CUDA, Sesame CSM via CPU — each wants different concurrency bounds).

**Dependencies.** Supervisor pattern (below) provides the measurement + execution substrate; this entry is the *policy brain* that decides what the Supervisor runs.

**Open question.** The interesting research question this deferred item implicitly asks is what I captured in STORY.md under "Open question — Apple Neural Engine + MPS scheduling under hybrid TTS load." Treat the answers there as input to this entry.

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

### ~~MCP sampling — combined UI + MCP server mode~~ — SHIPPED

Landed in Phase 2.4 as `--mode combined` on `pipeline.serve`. See DECISIONS #0034. Users with Claude Code configured via HTTP/SSE MCP get no-API-key parse. Hard-fails with clear setup guidance when no client is connected.

### MCP sampling — combined UI + MCP server mode (original entry below, preserved for context)

**What.** Run the UI and the MCP server in one Python process so that, when a Claude client connects to the MCP server, the UI's parse step can use `sampling/createMessage` to route LLM generation through Claude instead of requiring an API key. This is the third LLM provider option in the UI Settings screen ("Use my Claude app"), currently stubbed with a `ConfigurationError`.

**Why deferred.** Doing it right means (a) HTTP/SSE MCP transport so FastAPI and MCP can share the asyncio event loop without fighting over stdin/stdout, (b) lifecycle management for dropped MCP client connections mid-parse, (c) documentation + Claude config templates for users to register the HTTP MCP URL. Phase 2 ships separate-invocation mode which covers the two dominant workflows (API-key-in-UI, Claude-Code-drives-tools) — sampling is the third workflow that serves a smaller audience.

**When to revisit.** When a user actually hits the stub's `ConfigurationError` and wants the feature, OR when the MCP ecosystem standardizes on HTTP/SSE transport and combined mode becomes a common pattern.

**What the work looks like.**
- Add `python -m pipeline.serve --mode both` that mounts the MCP server on an HTTP/SSE route within the same FastAPI app.
- Implement `llm/mcp_sampling_provider.py::complete()` using the server's active `RequestContext.session.create_message(...)`.
- Document Claude Desktop / Claude Code config for HTTP MCP transport.
- Handle the "no client connected" case — UI should fall back to API key automatically if a client disconnects mid-parse.

### Per-character engine override in the UI (beyond narrator vs characters)

**What.** The split-voice-engine feature lets the user pick one engine for the narrator and another for all other characters. Beyond this: let the user override engine for a specific character via the voice picker sheet. E.g. narrator = kokoro, most characters = chatterbox, but this one dry-tone narrator-within-a-narrator character gets forced back to kokoro-bm_fable.

**Why deferred.** The existing cast-entry schema (`{voice, backend}`) already supports this; only the UI and the `propose()` function don't let the user reach it. Adds visual complexity to the voice picker sheet. Worth building once there's a real case where the two-bucket split isn't enough.

### Minor-character voice defaults

**What.** In the Phase 2 voice picker, when a character has < N lines (configurable threshold), skip the per-character picker and auto-assign from a small fallback pool. Threshold + pool are user-configurable in settings. Goal: don't make the user pick a voice for every walk-on — let the important characters get attention.

**Why deferred.** Depends on the Phase 2 UI existing. A CLI version of this isn't useful; users running `pipeline.run` already get auto-rank-1 for everyone.

**Parent.** Web UI + embedded MCP server.

### Cover extraction for non-EPUB formats + user confirm

**What.** For PDF and DOCX sources, scan for an image at the start of the document that could be a cover, then surface it on the UI for confirmation before embedding.

Specifically:
- **PDF**: extract images from page 1 (or the first few pages) using `pdfplumber.images` or `pypdfium2`. Pick the largest embedded raster image positioned near the top of the page, or the one that covers most of the page. Ignore small decorative elements (logos, page-number glyphs). If the first page is entirely a scanned full-page image (as with a book-dump PDF), that IS the cover.
- **DOCX**: extract inline images from the first paragraph / first section. python-docx can enumerate `document.part.related_parts` to find the image blobs.
- **None of these use an LLM** — pure heuristics, fast, deterministic.

**UI confirm flow.** When the ingestor finds a candidate cover, show it on the Options screen with a caption "Found this image at the start of your file — use as cover?" and buttons **Use it** / **Pick different** / **No cover**. Preserves the auto-detect convenience while giving the user an explicit veto. Unlike the EPUB case (where the EPUB spec unambiguously says "this IS the cover"), PDF and DOCX extraction is a guess — opt-in is the right default.

**Why deferred.** The EPUB case was the low-hanging fruit (spec-declared, zero guessing). PDF / DOCX cover extraction needs image-position heuristics, candidate ranking, and a new UI confirmation step. Its own chunk of work.

### Auto-generate a placeholder cover when none is available

**What.** When the ingestor finds no cover AND the user doesn't upload one, generate a simple library-bound-style cover via Pillow: dark background, title in a serif font at ~60% height, author name below in a smaller size, optional hairline frame. Written as an ImageDraw composition — no stock assets.

All output covers should be normalized to **1:1 aspect (square)** per audiobook standard (Audible convention — legacy of CD audiobook jackets that were square). Smart-crop when the source image is non-square: compute edge-energy saliency, find the densest N×N region, crop to it. Rule-based, no ML.

**Why deferred.** This is nice-to-have polish. A generated cover isn't a better product than a missing cover in most cases — and for users who care about their audiobook's cover, uploading one is a 2-second Options-screen click. Worth building once there's a clear cohort of users who want the auto-generated option.

### Cover upload on the Upload screen (front-of-flow)

**What.** Second drag-drop area on the Upload screen for optional cover art, so the user can configure cover + book in one interaction instead of discovering the cover option on the Options screen after a 30-second parse.

**Why deferred.** The Options-screen upload already covers the workflow. Front-of-flow is an ergonomic refinement; users who know they want a specific cover can set it in 2 clicks today.

### Cover override on the Done screen (post-render)

**What.** Re-package an already-rendered audiobook with a new cover without re-running TTS. Button on the Done screen: "Change cover." Re-runs just `pipeline.package` with the existing chapter MP3s and the new cover image. Fast (seconds, not minutes).

**Why deferred.** Covered by "upload a different cover on the Options screen, render again" today; the render IS cheap on a cache hit (per-line WAVs stay unchanged, only the package step runs). Worth building when we have a clearer signal that users forget covers until after render.

### Richer metadata from source → output

**What.** Extract and preserve full bibliographic metadata where available: publisher, ISBN, publication date, subject/genre, description, series name, series index. EPUB has these in `<dc:*>` tags; write them to the output audio-EPUB3 OPF manifest and to the m4b's MP4 metadata atoms where supported (date, genre, comment, album).

**Why deferred.** Phase 2.2 threaded the minimum — title, author, language. The rest of the Dublin Core metadata needs a consumer before it's worth building: Apple Books uses some; Audiobookshelf uses more; iTunes / Apple Music only uses a subset. Pick this up once there's a concrete player we're tuning for.

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

### Restructure as three distinct submodules: identification, casting, and voice library

**What.** The current `pipeline/cast.py` conflates three separable concerns into one file. The proposal is to split them cleanly:

**1. Cast identification** (`pipeline/cast_identify.py` or enriched `pipeline/parse.py` output)
Analyzes the parsed `script.json` and produces a structured casting brief:
- How many speaking characters, with line counts and gender/accent/age annotations (already present in `script.json` `characters[]`, but not surfaced as a summary).
- Whether the book is first-person narrated (narrator IS a character) — heuristic: same non-narrator speaker attributed > 40% of narration-adjacent lines, or `book_context` POV field.
- Speaking-line counts per character (to distinguish main cast vs background).
- Co-occurrence matrix: which characters appear in the same scene (needed for voice-uniqueness: two characters who never share a scene can share a voice; two who do, can't).
- Output: a `casting_brief.json` or an enriched field on `ScriptModel`.

We likely already compute most of this; the work is surfacing it explicitly as a first-class artifact rather than recomputing ad-hoc in `cast.py` and `validate.py`.

**2. Casting** (`pipeline/cast.py`, refocused)
Takes the casting brief and does two things:
- **Proposal:** For each character, query the voice library (see below) for top-N candidates matching gender/accent/age/personality. Rank by the existing `_score()` heuristic or by future LLM reasoning (see "LLM-driven casting" entry below).
- **Audition:** Render a ~4s sample for each proposal using the character's first actual dialogue line (not a stock sentence). Cache audition WAVs. Surface them in the UI. If the user rejects all proposals, fetch the next N from the library. If the user wants to supply their own clip, accept it (already wired via `POST /api/voice-reference`).

Key invariant: **casting is interactive**, not a one-shot proposal. The first proposals are a starting point, not a commitment.

**3. Voice library** (`pipeline/voice_library.py` or a `voice_library/` module)
Manages the full corpus of available voices across all backends:
- **Kokoro presets:** fixed list with known gender/accent/age/tag metadata.
- **Chatterbox reference clips:** `voice_samples/*.wav` with sourcing metadata, quality notes ("warm baritone, slight breath noise"), and known weaknesses ("struggles with short exclamations < 5 words").
- **Future: LibriVox index** (P0 auto-search dependency): every multi-cast LibriVox production indexed by character personality tags + audio quality score.
- **Future: user-uploaded clips:** promoted from `voice_samples/` with user-annotated metadata.
- Exposes a query interface: `library.find(gender, accent, personality_embedding, exclude_ids)` → sorted `Voice` list.
- Stores per-voice strength and weakness tags derived from listening notes and benchmark data (e.g. "good for: gravelly male, long sentences" / "bad for: short exclamations, female-coded names").

**Why this matters.** Currently when auto-cast collapses (same gender, all voices score ~equal), there is no structured "fetch more" path — the only escape is `--swap` or manual clip upload. A library with a query interface + weakness tracking means the casting step can filter known-bad matches and surface genuinely distinct options without manual LibriVox browsing.

**Why deferred.** The current structure works for books up to ~8 main characters. The refactor earns its complexity once the P0 auto voice-sample search (which requires the library layer) is ready to land — both should ship together. Building the library layer alone, without auto-search, adds infrastructure without closing a user-visible gap.

**When to revisit.** When the P0 auto voice-sample search is being implemented — that work requires the library abstraction. Design the library interface to satisfy both use-cases simultaneously.

**Dependencies.** P0 auto voice-sample search (consumer of the library query API). The identification submodule is largely a refactor of existing data — low risk, can land independently if useful for the co-occurrence uniqueness check.

### Voice-uniqueness invariant for main characters

**What.** A hard validator in `pipeline/validate.py::check_voice_consistency` (extending the existing speaker-in-cast check): no two **main characters** may share a voice ID. "Main" = speaker with ≥10 lines in `script.json` (threshold configurable in `config.yaml`). Supporting characters (<10 lines) may share stock voices — ideally the cast step rotates them per-scene to minimize *adjacent* overlap (e.g. Winnelin + Jesna co-appear in ch3 so must differ; Winnelin + Kimmalyn never co-appear so may share).

Render fails with an actionable error: *"Rig and Nedd both mapped to am_liam. Either `pipeline.cast --swap Rig <other>` or move one to Chatterbox with a reference clip."*

**Why deferred.** This is the logical enforcement layer for the cast-diversity guidance in CLAUDE.md. Hyperthief (2026-04-17) demonstrated the failure mode in production. Hardening needs a "what counts as main" threshold and a per-scene co-occurrence analysis for supporting characters, both of which are small but not trivial.

**When to revisit.** After the P0 auto voice-sample search lands — the validator and the search work together: search produces candidates, validator guarantees the user can't slip past it.

### First-person narrator / main-character tonal distinction

**What.** Auto-detect first-person narration: heuristic "same non-narrator speaker attributed >40% of narrator-like lines", or the LLM parse emits `script.book_context` with `pov: first_person_<character_name>`. When detected, the pipeline lets the narrator voice share a voice ID with the main character's dialogue voice — but applies a **tonal delta at render time** to distinguish interior ("narrator") from spoken ("dialogue") modes:
- Kokoro `speed` shift (±5% — narrator slightly slower, more thoughtful; dialogue at natural pace).
- Light processing overlay (narrow-band EQ + gentle compression to simulate "interior thought" vs "spoken aloud" — like a radio drama narrator behind a thin filter).
- Optional subtle pitch shift (±2 semitones).
Config knob per book in `cast.json` or `config.yaml`.

**Why deferred.** Hyperthief is third-person close-POV, not first-person, so this didn't apply. Gatsby is first-person (Nick) but the user didn't flag it. Earns its complexity the first time we render a first-person novel where the reader complains that narrator-Nick and dialogue-Nick sound identical and it's jarring.

**When to revisit.** First first-person rendering that draws user feedback about narrator/main-character voice ambiguity. Implementation will need to coexist with the voice-uniqueness invariant above (the invariant needs an explicit exception for POV character when this flag is on).

### Expand Chatterbox reference library to the P&P cast

**What.** Same LibriVox-sourcing pattern applied to Karen Savage's (or another) solo reading of P&P — extract refs for Darcy, Elizabeth, Mr. Bennet, Mrs. Bennet, Lady Catherine, etc. Enables running P&P scenes through Chatterbox if a scene needs more emotion than Kokoro delivers.

**Why deferred.** The Austen Kokoro voices work for the current P&P scenes. Only worth doing when we're rendering an Austen scene where Kokoro falls flat (e.g., Mrs. Bennet at her most hysterical, Lady Catherine at her most imperious — characters whose comedy lives in vocal modulation).

### SOURCES.md → a proper catalogue

**What.** Today `voice_samples/SOURCES.md` lists two clips. If the library grows past ~10, it wants per-clip metadata in a parseable format (JSON/YAML) that can feed the audition UI.

**Why deferred.** Two clips is not a catalogue.

### Voice dataset matching via jim-schwoebel/voice_datasets

**What.** The curated dataset list at https://github.com/jim-schwoebel/voice_datasets catalogs ~70+ open-licensed speech corpora spanning many accents, ages, genders, and speaking styles. Audit it to find datasets that could expand our reference clip library — particularly for Chatterbox/Sesame, where the reference clip is the primary voice identity signal.

**Why deferred.** Current LibriVox-sourced clips cover the stories we've actually rendered. Dataset expansion only earns its complexity when we run out of suitable LibriVox voices for a new cast.

**When to revisit.** When a new character needs an accent, age, or gender profile that no LibriVox reader we've sourced covers well. Or when the cast library grows and we want a structured sourcing process.

### Reuse voice cast from an imported book

**What.** Let users carry a previously-approved `cast.json` into a new book's casting step, so returning characters (or similar character archetypes across books) get the same voices without re-audition.

Two phases:
- **Ph-1 (same service).** When the user uploads a new book through the UI, surface a "Use cast from a previous project" option that lists prior projects stored in `build/`. Load that project's `cast.json` and pre-fill matching character names; unmatched characters fall back to normal auto-cast. Schema compatibility is guaranteed since both projects used this pipeline.
- **Ph-2 (external audiobook).** Let the user upload an existing audiobook (M4B/MP3) and a companion `cast.json` or manually map characters to clips extracted from the audio. The extracted clips become reference clips in `voice_samples/`; casting proceeds normally from there.

**Why deferred.** We've only rendered single standalone stories so far; the "returning cast" use case hasn't come up. Ph-2 requires clip extraction from arbitrary audio, which is a new ingest surface.

**When to revisit.** First multi-book project, or when a user explicitly asks to preserve voices across two stories with overlapping characters.

### Series cast continuity prompt

**What.** When the user uploads a new book, detect if it belongs to the same series as a previously-rendered project (by comparing `script.json::book_context.series` or a user-supplied series tag). If a match is found, prompt: "This looks like it's in the same series as *[prior book]*. Use the same voice cast?" — with options to accept, cherry-pick by character, or start fresh.

**Why deferred.** Needs: (a) a reliable series-identity signal in the parsed script (LLM-extracted vs. user-supplied — unclear which), (b) prior project lookup (ties to the cast-import feature above), and (c) UX for the confirmation step. More product thinking needed before this is ready to spec.

**When to revisit.** After Ph-1 of "Reuse voice cast from an imported book" ships — series detection is a logical extension of the same cast-persistence infrastructure. Also needs a real user story (two books in the same series attempted by one user).

**Dependencies.** "Reuse voice cast from an imported book" Ph-1 must exist first.

### Emotion-keyed reference clips per character

**What.** A character who needs genuine emotional range (joyful → furious → sobbing) cannot be served by one reference clip + Chatterbox's exaggeration slider. The slider modulates intensity *within* a register; it cannot shift the register itself. The solution is multiple reference clips per character — one per emotional extreme — selected at render time based on `line.emotion.label`.

`cast.json` schema extension (emotion map replaces single voice string):
```json
"Daisy": {
  "default":  { "voice": "daisy_neutral",  "backend": "chatterbox" },
  "joy":      { "voice": "daisy_joyful",   "backend": "chatterbox" },
  "angry":    { "voice": "daisy_angry",    "backend": "chatterbox" },
  "sad":      { "voice": "daisy_sobbing",  "backend": "chatterbox" }
}
```

`render.py` selects the clip matching the line's emotion label; unlisted emotions fall back to `"default"`.

**Sourcing constraint.** All clips for one character must be from the **same speaker** — swapping speakers mid-character breaks voice identity. Two routes:
- **LibriVox route** (preferred): same reader performing the character across multiple emotional scenes in the source book. Extract one clip per register. Identity + personality both preserved.
- **CREMA-D / RAVDESS route**: same actor across their emotion-labeled recordings (91 actors × 6 emotions in CREMA-D; 24 actors with high-intensity sad/fearful in RAVDESS). Full range ready-made but no personality signal — voice type match only.

**Status (2026-04-17).** Pressure-tested in a throwaway worktree (`experiment/emotion-ref-clips`, discarded). Four strategies rendered head-to-head on a 13-line FM+Rig excerpt from Hyperthief ch01: A=control single-clip, C=CREMA-D, D=RAVDESS, E=text-prefix `(warmly)` cues. B (LibriVox-multi) was not rendered — no Hyperthief LibriVox source audio exists, sourcing is blocked at content availability.

**Three paths marked DEAD-END on the Chatterbox backend:**

- **C — CREMA-D cross-actor dataset clips.** Dead end. QA 7/13 (RMS/clipping/silence failures). Listening: low volume, noisy. Cause: acoustic mismatch — CREMA-D is 16 kHz booth-recorded, different mic/room/loudness than Chatterbox's training distribution. Persona also collapses: same-gender characters share one actor's timbre. Per-clip loudnorm + spectral matching could salvage it in principle; not worth the engineering against strategy B as a cleaner option.
- **D — RAVDESS cross-actor dataset clips.** Dead end for direct-clip use. QA 6/13, same studio-mismatch artifacts as C. *One positive signal worth remembering:* tonal delivery was more natural than CREMA-D. The usable part is the **prosody**, not the full clip — suggests a voice-conversion path (RVC / so-vits-svc) that transfers RAVDESS prosody onto a LibriVox persona clip. That's a separate research spike, not a clip-map change.
- **E — text-prefix `(warmly)` / `(sadly)` cues on Chatterbox.** Dead end. QA 12/13 (clean) but listening reveals Chatterbox speaks the cue word literally before every sentence. Cause: Chatterbox is a pure acoustic learner with no stage-direction parser. Dia and Orpheus DO parse these tags natively — strategy E is trivially correct on those backends, dead on this one. Not a sourcing problem, a backend-capability problem.

**Only unfalsified path: B — LibriVox-multi, same-reader emotional registers.** Unvalidated because Hyperthief has no LibriVox recording. Still theoretically sound where source material permits. Gatsby is the one book in the current backlog where B could be tested cheaply (`voice_samples/_librivox_src/` already has the MP3s and `SOURCES.md` documents extraction timestamps). Budget: ~20 min/character of Whisper-assisted timestamp hunting + ffmpeg extract.

**Sourcing-cost deltas** (for the next reader — don't re-derive):

| Strategy | Per-character labor | One-time setup |
|---|---|---|
| A (control) | 0 | 0 |
| B (LibriVox-multi) | ~20 min | find a matching-reader PD/CC audiobook |
| C (CREMA-D) | 0 | ~5 min scripted download (git-lfs via `media.githubusercontent.com`) |
| D (RAVDESS) | 0 | ~5 min Zenodo download (CC BY-NC-SA, speech archive 208 MB) |
| E (text-prefix) | 0 | 0 — code-only, but blocked on non-Chatterbox backend |

**What to revisit first.** Before attempting any of this again, check whether Dia-on-MPS has shipped (see the Dia entry elsewhere in this file). Dia's native `(whispers, trembling)` tag parser subsumes strategy E at zero sourcing cost with the existing `line.emotion.label` + `line.emotion.notes` fields. Until that lands, this whole category (`cast.json` voice-map extension + render.py clip selection) stays off the roadmap — the schema change is cheap (~25 LOC) and can be re-added in a day when the right backend exists.

**Follow-on candidates** surfaced by the experiment (each worth its own BACKLOG entry when prioritized):
- Dia MPS integration — evaluate as soon as the candidate branch is ready; it's the real unlock for emotion control.
- Voice-conversion prosody transfer — RAVDESS-style emotion onto LibriVox timbre. Research spike, one new pipeline stage.
- Acoustic-matching preprocessor for foreign reference clips — per-clip loudnorm + spectral adaptation. Would rescue strategies C/D if someone still wanted to try them; currently lower priority than Dia.

### Demographic reference clip set

A set of 10 ready-made reference clips (sourced April 2026) covering demographic profiles not easily found in LibriVox dramatic readings:
- Young male, England (20s); Male 50s/60s/70s, US; Male 70s, Scottish
- Female (various — 60s US ×2, older US, unspecified); Teen female, England/Cheshire

**Source.** Google Drive folder: `https://drive.google.com/drive/folders/1pzWiCB8K67Az_iT2iS3vAc-UjbyUkP9K`

**License.** Posted on Reddit (r/StableDiffusion) as free-to-use TTS/Chatterbox voice samples. Thread: `https://www.reddit.com/r/StableDiffusion/comments/1m6jedq/voice_samples_library_for_tts_chatterbox_oute/`

**Usage.** Demographic matching only — no personality signal. Useful when LibriVox has no reader matching the required age/accent profile. Download + normalize to 24 kHz mono via ffmpeg; add to `voice_samples/`; document the Reddit thread URL in `SOURCES.md`.

---

## QA / eval

### Multimodal LLM listener (Gemini 2.5 Pro with audio input)

**What.** Pass the rendered m4b to Gemini and ask "does this character sound angry on line 14? Does the narrator pace feel natural?" — an actual AI ear, not a transcription check.

**Why deferred.** Requires API key + network + per-request cost; current Whisper round-trip + mechanical QA catches the failure modes we've actually seen. The remaining failure mode ("does it sound emotionally right") is exactly what the human ear is good at — promoting a machine to judge it is speculative.

**When to revisit.** When bulk rendering (entire novels) makes per-chapter human listening impractical.

### Automatic QA-threshold calibration

**What.** QA flagged two Hunsford lines at the threshold boundaries (peak −1.0 dB, pacing below 1.3 w/s on a 3-word sentence). Thresholds are hand-picked from audiobook industry lore; they should adapt to the distribution of lines we actually render.

**Why deferred.** Two false positives in a month of renders is signal, not noise. When the false-positive rate climbs, calibrate.

---

## Post-processing

### Contextual room effects (echo / reverb / radio crackle / outdoor space)

**What.** Emotion- and scene-tag-driven post-FX applied per-line after TTS, before chapter concat. Examples:
- Radio lines (flightleader-on-comms, dispatch, etc.) → narrow-band EQ + light crackle + slight compression, so "Skyward Two, ready" over Arturo's radio sounds unmistakably like a radio.
- Large-room / warehouse / cathedral scenes → slight convolution reverb or algorithmic room reverb.
- Outdoor / open-air → light air reverb + optional wind bed at very low level.
- Intimate / whispered / interior-thought → close-mic'd EQ + gentle compression.

**Detection signal.** Two options (not mutually exclusive):
1. Infer from `emotion.notes` — grep for tags like "(radio)", "(whispered)", "(indoor echo)" that the LLM parser already tends to write.
2. Explicit scene tag on `LineModel`: add optional `scene: Literal["radio", "outdoor", "indoor_large", "intimate"] | None`. LLM parser learns to emit this from dialogue context ("said over the radio", "shouted across the courtyard").

**Implementation.** sox or ffmpeg filter chain applied inside `pipeline/render.py` right after the TTS backend returns bytes, keyed off the scene tag. Keep chains short and cheap (<50ms per line) so render wall-clock doesn't balloon.

**Why deferred.** Orthogonal to the voice-diversity P0. Low risk, medium value — makes finished audiobooks feel more produced — but no one has flagged it as a blocker. The Hyperthief radio scenes (Arturo calling in over comms) would be the obvious first win.

**When to revisit.** After the P0 voice-search lands and the Hyperthief-class "identical voices" problem is truly closed. OR when a specific scene's lack of spatial cue is called out ("why does Arturo on the radio sound like he's sitting next to Nedd?").

### Chatterbox short-text artifact — detection + mitigation

**What.** Chatterbox's diffusion sampler requires a minimum amount of input text to stabilize. Inputs ≤10 characters (e.g. `"Hey!"`, `"Scud."`, `"What?"`) reliably produce garbled, hallucinated output — 10 consecutive take-attempts on Rig's `"Hey!"` during Hyperthief v2.1 all produced irrelevant phrases (`"here it is"`, `"im looking forward to it hey"`, `"youre lucky"`, etc.) with Whisper similarity 0.0-0.32. No amount of stochastic retry fixes it; the floor is the model's token-length conditioning.

**Impact.** Any book with a short exclamation (greetings, interjections, short retorts) in a character's dialogue line will garble. Hyperthief has at least 6 such lines.

**Mitigations, ordered by complexity:**

1. **VAD-split from a longer rendered text.** Render the character's neighbouring dialogue fragments as ONE Chatterbox call (e.g. `"Hey!" "Um, happy birthday?"` rendered as one utterance), which gives Chatterbox enough tokens to stabilize. Use ffmpeg `silencedetect` filter to find the silence between phrases, crop to individual WAVs, install each as its own cache entry. Preserves faithful-wording at script level; the cache content diverges from strict per-line hash semantics but the audio output is what matters.
2. **Text-padding-then-truncate.** Render `"Hey!" he replied.` as one call (long enough to stabilize) and use silencedetect to crop to just the first word. Only works when the padding happens to produce a natural pause.
3. **Fallback to Kokoro for short lines.** When Chatterbox would render a line ≤10 chars, fall back to the character's nearest Kokoro preset for THAT line only. Voice timbre jumps for one word but at least the audio is correct. Requires a `fallback_kokoro_voice` field per Chatterbox cast entry, or auto-picked from the character's gender/age.
4. **Retry with Whisper-similarity gate** (also useful beyond this short-text case — see the parallel QA sanity check item). Render N takes, transcribe each, accept the first one whose similarity to expected text exceeds threshold. On ≤10-char lines this often still fails (Chatterbox stuck in a local minimum) — the 10-take Hyperthief data showed best-of-10 sim ≤0.32 for `"Hey!"`. So retry is necessary but not sufficient; it's the CANARY that triggers fallback strategies (1)-(3).

**Why deferred.** The v2.1 one-off fix for Hyperthief used mitigation (1) by hand on the single `"Hey!"` line. Productizing any of (1)-(3) needs a classifier (when is a line "too short"?) and a fallback path in the render loop. Belongs with the parallel QA sanity-check item below — same hooks, same infrastructure.

**When to revisit.** Next render that trips a short-line garble detected by the parallel QA sanity check. Or proactively during the supervisor-pattern implementation — same time we gain per-request telemetry.

### Parallel QA sanity check for synthesized dialogue

**What.** After each line synthesizes, run a Whisper round-trip on the line WAV in a side thread (or worker pool) while the next line synthesizes. Compute similarity between Whisper's transcription and the expected `line.text`. If similarity < threshold, the line is flagged as failed. Policy on failure:
- Retry with perturbed emotion.intensity (±0.05) to change the Chatterbox generation
- After N retries (config, default 3), either keep the best-of-N take, or fall back to Kokoro (see Short-text artifact item above)
- Log every failure with line id + expected + transcribed so the operator can audit after the render completes

**Why this is the right abstraction.** Whisper is CPU-bound, Chatterbox is GPU/MPS-bound. They share no meaningful hardware resource, so running them concurrently is a near-free 1.3-1.5× effective throughput gain on long renders — UNLIKE two-Chatterbox-process parallelism which regressed 38% due to MPS serialization (documented elsewhere in BACKLOG and STORY). This is the "safe" parallelism we failed to spot on Hyperthief v2.

**Implementation surface.**
- `pipeline/qa.py` already has `whisper_roundtrip` — reuse its transcription code.
- Add `pipeline/_qa_worker.py` with a thread-safe queue; producer is `render_chapter` (enqueue after each line), consumer is the QA worker (dequeue, transcribe, compute sim, report).
- Retry loop sits in `render_chapter`: it pops failed-line signals between lines, re-synthesizes affected lines, re-enqueues for re-check.

**Why deferred.** Meaningful architecture work: queue design, retry state, integration with the supervisor pattern (which owns concurrency budgets). The Hyperthief v2.1 used a one-shot 10-retry script by hand. Productize when the next book trips this.

**When to revisit.** After Part B's voice-uniqueness validator + per-line timing ship (those are the prerequisite hooks). Or when user listens to a render and flags another garbled line.

### Chorus overlap / unison stacking for group-speaker lines

**What.** When multiple characters speak in unison (slug chorus "SURPRISE!", "HAPPY BIRTHDAY!", "Thank you!"), render the line with 3-5 different voices layered (slight pitch jitter, slight time offset <50 ms) and sox-mix to produce a real "chorus" effect, instead of a single voice saying the line alone. Detected from a `speaker: "slugs"` / `speaker: "crowd"` marker or an explicit `chorus: true` flag on `LineModel`. Mixing parameters: 3–5 voices, per-voice random pitch ±3%, per-voice random offset 0–80 ms, per-voice random gain −2 to −6 dB except one "lead" voice at 0 dB.

**Why deferred.** Current workaround for Hyperthief render of 2026-04-17: the `slugs` chorus is rendered once in `af_sky`. User noted the SURPRISE! / HAPPY BIRTHDAY! lines don't feel like a chorus. Cheap to implement (one sox/ffmpeg multi-input filter chain) but needs decision on where to do the multi-render (render.py post-TTS hook, or a separate chorus.py step) and on the voice-selection algorithm (rotate through per-slug assignments? random N of the Kokoro preset pool? use the cast-declared per-slug voices Clink/Gill/Nuts/Chubs layered?).

**When to revisit.** Any future render with a named chorus speaker. For Hyperthief specifically, if a re-render is commissioned and the slug reveal scene bothers the listener. Short implementation — can probably ship with the next small pipeline PR.
