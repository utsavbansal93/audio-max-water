# Changelog

All notable changes to this project will be documented here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed — accept wrapped-in-folder EPUB uploads (macOS Finder / browser drag-drop)

- `ui/app.py::_looks_like_epub_zip` now returns `(is_epub, prefix)` and detects two layouts: (A) spec-compliant root-level `mimetype` entry; (B) all entries wrapped in a single top-level folder, with `<folder>/mimetype` matching `application/epub+zip`. Layout B is what macOS Finder's Compress and browser drag-drop-of-a-directory produce.
- `ui/app.py::_rewrite_wrapped_epub_zip` strips the wrapper prefix from every entry and writes a fresh spec-compliant ZIP (`mimetype` STORED first, everything else DEFLATED, atomic replace).
- `_save_upload` re-roots wrapped uploads transparently, so `EpubIngestor` sees a normal `.epub` and needs no changes.
- Error message sharpened: "This .zip isn't an EPUB. We check for a `mimetype` file with contents `application/epub+zip`, either at the root of the zip OR inside a single top-level folder."
- Root cause of the earlier "drag my Hyperthief.epub folder and got rejected" report: the browser's drag-drop zip preserves the top-level folder; our sniff only looked at the ZIP root. Python's `zipfile.ZipFile.write(p, p.relative_to(src))` (what I used in the Phase 2.2 smoke test) was the unrepresentative case.
- `__MACOSX/` prefixed entries (macOS resource forks that Finder's Compress occasionally creates) are ignored during the single-root-folder detection so they don't trip the "multiple top-levels" check.

### Added — author + language + auto-cover extraction (Phase 2.2 metadata)

- `pipeline/ingest/base.py::extract_author_from_text` — scans the opening ~800 chars / 25 lines of a source for a byline (matches "by X", "written by X", "a novel by X", "author: X", optional italic markers, case-insensitive). Refuses matches longer than 100 chars or ending in connectors ("and", "or", "the") to avoid mid-prose false positives. Motivated by the user's observation that PDF / DOCX metadata-author fields are frequently wrong — stamped by zippers, converters, and default OS accounts instead of the real author.
- `pipeline/ingest/base.py::clean_metadata_author` — sanity-checks document-metadata author strings against a ban-list of well-known tool names (Calibre, Adobe, Microsoft Office User, Pages, zipper, LaTeX, etc.). Returns None when the value is banned or too long to be a real name.
- `pipeline/ingest/pdf_ingestor.py` now prefers text-based byline extraction; falls back to cleaned PDF metadata only when text extraction finds nothing. The source's own title page is the authority.
- `pipeline/ingest/docx_ingestor.py` same pattern — text-first, ban-listed `core_properties.author` only as fallback.
- `pipeline/ingest/epub_ingestor.py` keeps metadata-first (EPUB `<dc:creator>` is publisher-authored and reliable), but runs the text scanner as a cross-check; when metadata fails the ban-list, text wins.
- `pipeline/ingest/base.py::RawStory` gains a `language` field; default `"en"`. Populated from EPUB `<dc:language>` (stripped to 2-letter code).
- `pipeline/ingest/epub_ingestor.py::_extract_cover_from_book` — automatically extracts the cover image from EPUB sources. Resolution order: (1) EPUB3 `properties="cover-image"` manifest item; (2) EPUB2 `<meta name="cover" content="<X>"/>` where `<X>` can be either an item id OR a filename (the spec says id, but Sigil and many other editors write filenames — we handle both); (3) filename heuristic for items named "cover". Robust to ebooklib's `ITEM_IMAGE` type-tag bug by checking media-type strings directly.
- `pipeline/parse.py::parse_to_disk` persists extracted cover bytes to `<build_dir>/source_cover.<ext>` when the ingestor found one; patches `ScriptModel.author` from `raw.author` when the LLM reported "unknown" and the ingestor has a better value; same for `language`.
- `pipeline/run.py::_find_source_cover` — helper used by the CLI orchestrator to locate `source_cover.*` in a build dir. Auto-used as the cover when the user didn't supply `--cover`.
- `pipeline/schema.py::ScriptModel` — new `author: str = "unknown"` and `language: str = "en"` fields (both default-valued, so old `script.json` files still parse).
- `pipeline/package.py::build_m4b` — new `language: str` kwarg; writes `artist`, `album_artist`, `language` (ISO 639-2 via a small mapping), and `genre=Audiobook` to the m4b's FFMETADATA. `package()` dispatcher threads the kwarg through.
- `pipeline/epub3.py::build_audio_epub3` — new `language: str` kwarg; replaces the hard-coded `<dc:language>en</dc:language>` with the parsed value.
- `prompts/parse_story.md` — schema updated with `author` and `language` top-level fields so the LLM is primed to populate them from the source.

### Added — Phase 2.2 UI

- `GET /cover/<job_id>` FastAPI route — serves the job's cover image (user-uploaded via Options screen if present, else the auto-extracted `source_cover.*`).
- Options screen shows an inline cover preview when a source cover was extracted: "Using the cover from your file — upload a replacement below, or leave blank to keep this one." Replaces nothing; the file picker still accepts a user override.
- Options screen shows the detected author in a Metadata card: "Detected from your file." Transparent about what's being set; the user can notice a wrong auto-detect and fix by manual override (backlog: inline edit).
- `ui/services/session.py::Job.public_view()` now exposes `author`, `language`, and `source_cover_available` to templates.
- `ui/app.py::_start_render` passes `script.author` + `script.language` + resolved cover (user upload wins, else source cover) to `package()`. Metadata flows end-to-end through the web UI path too — not just the CLI.
- CSS: `.cover-preview-row` + `.cover-preview` for the 96×96 preview image on Options.

### Backlog additions

- Cover extraction for non-EPUB formats (PDF page-1 image, DOCX inline images) with user-confirm UX.
- Auto-generate placeholder cover (library-bound Pillow render with title + author) when no cover is available + smart-crop to 1:1 Audible-standard square.
- Cover upload on the Upload screen (front-of-flow) — today's Options-screen upload works; backlog captures "let me do this up front."
- Cover override on the Done screen — re-package without re-rendering.
- Richer metadata preservation: publisher, ISBN, publication date, subject/genre, description, series — from EPUB `<dc:*>` into audio-EPUB3 output and m4b MP4 atoms where supported.

### Fixed — upload handling for directory-form EPUBs + inline error rendering

- `ui/app.py::_save_upload` now accepts `.zip` uploads and sniffs the container: if it's a valid EPUB (has an uncompressed `mimetype` entry reading `application/epub+zip`), promote to `.epub` and proceed; otherwise reject with a clear 400 explaining what the zip was missing. Motivated by the common case of a `.epub` on disk that's actually an unzipped directory — browsers auto-zip it on drag-drop and the server was rejecting the resulting `.zip` with an unhelpful error page.
- `pipeline/ingest/epub_ingestor.py::EpubIngestor.ingest` detects directory-form EPUBs (path is a directory containing `mimetype` + `META-INF/container.xml`) and zips them to a temp file before handing to `ebooklib` — matches EPUB 3.3 OCF layout (mimetype STORED first, everything else deflated). Same fix covers the CLI case: `python -m pipeline.run --in foo.epub/` now works when `foo.epub` is a folder.
- `pipeline/ingest/__init__.py::get_ingestor` routes directory paths with `.epub` suffix to `EpubIngestor`.
- `ui/static/app.js::initUpload` now submits via `fetch()` instead of native form POST. On failure the server's `{"detail": "..."}` JSON renders inline in a new `#upload-error` banner on the upload page; on success the browser navigates to the redirected `/parsing/<job>` URL. No more dead-end blank pages showing raw JSON.
- Client-side extension gate rejects obviously-unsupported files without a round-trip; `.zip` is let through for server-side sniffing.
- `ui/templates/upload.html` gains the `#upload-error` banner placeholder and widens the `<input>` `accept` attribute to `.zip,application/epub+zip` so the OS file picker offers directory-form EPUB zips.
- `ui/static/style.css` adds `.banner--error` modifier (uses the existing `--danger` token) with a subtle spring shake on first show.
- `pipeline/validate.py::_normalize` — the `*by Author*` byline stripper now matches inline (not just as its own line). Parse-step LLM responses often concatenate the byline into the opening narrator line; without this fix, the validator saw a byline in the reconstructed text but not in the normalized source and complained. Regression surfaced when parsing Hyperthief (an EPUB with a `*by Brandon Sanderson*` byline directly under the title).

### Added — Phase 2.1 job persistence + stage tracker + resume + history + EPUB front-matter filter

- `ui/services/job_store.py` — disk-backed job persistence. `PersistedJob` dataclass carries everything we record about a job (status, paths, per-stage state with timestamps + progress counters). `JobStore` writes each job to `build/_jobs/<job_id>.json` atomically (write-temp-then-rename). Jobs survive server restarts.
- `ui/services/job_store.py::detect_last_good_stage` — walks a build directory and reports the first stage whose artifacts are missing. The resume endpoint uses this to decide where to restart.
- `ui/services/session.py::Job` rewritten to wrap a `PersistedJob` and auto-save on every state transition (`status`, `error`, stage updates). Runtime-only state (asyncio.Queue, worker thread, in-memory Script/Cast models) stays non-persisted.
- `ui/services/session.py::Job.apply_event()` — translates each `ProgressEvent` into a stage update and saves it. Every SSE event now also mutates disk state, so the history page + resume logic are trivially aware of where a job got to.
- `ui/services/session.py::Job.hydrate_artifacts()` — lazy-load `script.json` / `source.md` / `cast.json` from disk when a job is resumed mid-pipeline.
- `ui/app.py` lifespan — on startup, scan all persisted jobs; any stuck in "parsing" / "rendering" / "voices" gets rescued to status="error" with a friendly message ("Job was interrupted… Click Resume to continue"). The most-downstream "active" stage is the one marked error; earlier active stages are retroactively marked "done" if a later stage already completed.
- `/history` page + `/api/resume/{job_id}` + `/api/job/{job_id}/delete` endpoints. History lists every persisted job with input filename, provider + backend + format, per-stage dots, status badge, and action buttons (Resume / Download / Open / Delete).
- `_start_parse()` accepts `skip_to` so a resumed job can jump straight to cast (script.json already on disk) — leverages existing content-hash caches in `parse_to_disk`, `cast.propose`, and `render.render_all`.
- `pipeline/parse.py::parse_to_disk` accepts `on_progress` callback; emits `ingest:start`, `ingest:done`, `parse:start`, `parse:done` events so the UI's stage tracker reflects the ingest/parse boundary (previously the UI showed ingest "active" forever because parse_to_disk handled it opaquely).
- `ui/templates/_stage_tracker.html` + `history.html` — reusable stage-pill component (pending/active/done/error/skipped states with live progress bar on the active stage) and history list with per-job action row.
- `ui/static/style.css` — stage tracker styles (pulsing active indicator, accent-color progress fill beneath active pill, checkmark on done, exclamation on error, dashed circle on skipped). History list with status badges + per-job border accent. Mini "stage dots" for compact history rows.
- `ui/static/app.js::subscribeProgress` rewritten to update the stage tracker in place from SSE events (pill status + inline progress bar + stage title + overall progress fill), with configurable terminal-stage redirect semantics via `doneRedirect` + `terminalStages`.
- `pipeline/ingest/epub_ingestor.py` — front-matter filter. Skips cover / title page / copyright / TOC / colophon / imprint / index / bibliography / appendix sections via three signals: `epub:type` attribute (body vocab wins), filename pattern (`cover.xhtml`, `titlepage.xhtml`, `toc.xhtml`, etc.), and TOC entry title ("Cover", "Copyright", "Contents", …). Preserves preface / foreword / introduction / dedication / epigraph / prologue / epilogue / afterword / chapter-labeled sections — the user listens to *content*, not metadata. Body-signal detection (filename or title matches `dedic|preface|foreword|introduction|prologue|chapter|part|book`) takes precedence over frontmatter signals so "dedication.xhtml" is kept even though boilerplate detectors would otherwise skip it. Emits a `warnings.warn` listing what was skipped so the user can see what didn't make it into the audiobook.
- `BACKLOG.md`: "URL ingestor — paste a link". Deferred because article extraction from arbitrary HTML is a substantially different reliability problem than file ingest.

### Changed — Phase 2.1
- `pipeline/run.py::run` threads its `on_progress` callback into `parse_to_disk`, so CLI runs now emit per-stage events too (before, only the UI saw ingest/parse events because the orchestrator fired its own start markers outside).
- The topbar gets a "History" link (was just the gear-icon for Settings).

### Added — Phase 2 web UI + MCP server

- `pipeline/serve.py` — launcher. `python -m pipeline.serve --mode ui` starts the local web UI on `http://127.0.0.1:8765`; `--mode mcp` starts the MCP server over stdio for Claude Code / Claude Desktop integration.
- `ui/` package — FastAPI app with five Apple-HIG-flavored screens (Upload → Voices → Options → Rendering → Done) plus Settings. HTML via Jinja2, Server-Sent Events for live progress, zero-JS-build static assets.
  - `ui/app.py` — all routes in one file (pages + API + SSE stream); sync pipeline calls are offloaded to worker threads so uvicorn's event loop stays responsive.
  - `ui/services/settings.py` — persisted settings at `~/.config/audio-max-water/settings.toml` (0600 perms). LLM provider, API keys, default backend + format, theme. Env vars always win over the saved file.
  - `ui/services/session.py` — single global `Job` (local-first, one user, one in-flight render) with a `public_view()` that produces a JSON-safe snapshot for templates.
  - `ui/services/progress.py` — threadsafe SSE emitter; wraps `ProgressEvent` instances from the pipeline into `event: <stage>:<phase>\ndata: <json>` frames.
  - `ui/services/audition.py` — voice audition: synthesize a short WAV of `text` read by `voice_id`, cached on disk at `~/.cache/audio-max-water/auditions/<hash>.wav`.
  - `ui/services/backend_pool.py` — **process-wide** singleton cache for TTS backends, shared across cast proposal, audition, and render. Loading MLX Kokoro twice in one process corrupts the pipeline (`[Errno 32] Broken pipe`); the pool lock guards both load and synthesize so concurrent HTTP handlers and the render worker don't step on each other.
- `ui/templates/` — base + 7 screens: `upload.html`, `settings.html`, `parsing.html`, `voices.html`, `options.html`, `rendering.html`, `done.html`. Progressive disclosure (advanced options collapsed), no jargon ("Audiobook" / "Ebook with synced audio"), 44pt tap targets, single-accent-color buttons.
- `ui/static/style.css` — Apple-HIG-derived stylesheet. Typography-first (SF Pro system stack, weight 300 headers), 12pt card radius + 8pt buttons + 6pt inputs, single accent color (#007AFF / #0A84FF), native `prefers-color-scheme` dark/light with matching explicit `[data-theme="light"|"dark"]` overrides, spring-easing motion, `prefers-reduced-motion` respected.
- `ui/static/app.js` — vanilla JS (~300 LOC, no framework, no build). Drag & drop uploader, SSE progress subscription with auto-redirect on stage completion, voice picker `<dialog>` sheet with audio playback + spring animations, accessible keyboard focus, global error banner.
- `pipeline/mcp_server.py` — MCP server exposing 5 tools: `run_pipeline` (one-shot end-to-end), `parse_only` (ingest + parse → script JSON), `list_voices`, `audition_voice`, `supported_formats`. Uses the `mcp` Python SDK over stdio. Tools offload sync pipeline work to `asyncio.to_thread` so the stdio event loop stays responsive.
- `llm/mcp_sampling_provider.py` — stub provider for the UI's "Use my Claude app" option. Currently raises `ConfigurationError` with a setup-instructions hint; the real implementation needs a combined UI+MCP launcher (filed in backlog as "MCP sampling combined mode").
- `pipeline/_events.py` — `ProgressEvent` dataclass + `ProgressCallback` type + `emit()` helper. Fire-and-forget — callbacks can't break a render.

### Changed
- `pipeline/render.py::render_chapter` and `render_all` gain optional `on_progress: ProgressCallback` kwargs. Default None = silent (CLI unchanged). The web UI wires this into its SSE queue; each chapter emits `stage:"render" phase:"start|progress|done"` events with `current / total / chapter / total_chapters` fields.
- `pipeline/render.py::render_all` also accepts `backends: dict[str, TTSBackend] | None`. When the UI passes its shared backend pool, MLX / Chatterbox load exactly once per process; without it the behavior is unchanged (fresh cache per call).
- `pipeline/run.py::run` accepts `on_progress` and emits stage-boundary events (`ingest:start`, `parse:done`, `cast:start`, etc.) so the UI gets uniform progress regardless of which stage is running.
- `pipeline/cast.py::propose` accepts an optional `backend: TTSBackend` kwarg so the UI's shared pool is reused for audition rendering. Default path (None) is unchanged.
- `llm/__init__.py::get_provider` now accepts `"mcp"` as a provider name, dispatching to `MCPSamplingProvider`.
- `pyproject.toml` `[ui]` extra already had FastAPI + uvicorn + Jinja2 + multipart + mcp from the Phase 1 prep; installing `-e '.[ui]'` is now the correct command for Phase 2.

### Added — Phase 1 pipeline-ification (orchestrator + multi-format ingest + audio-EPUB3 + cover art)

- `pipeline/run.py` — end-to-end orchestrator. One command: `python -m pipeline.run --in <file> [--format m4b|epub3] [--cover <img>]` chains ingest → parse → cast (auto-propose + auto-approve) → render → qa → package with no human-in-the-loop. Measures + logs stage timings; gracefully skips optional steps (Whisper QA) when deps are missing; hard-fails with an install command on required missing deps.
- `pipeline/ingest/` package with an `Ingestor` ABC (mirrors `TTSBackend` pattern) and concrete implementations per format: `text_ingestor.py` (`.txt`, stdlib-only), `markdown_ingestor.py` (`.md`, H1/H2 chapter detection), `docx_ingestor.py` (python-docx, Heading 1/2 style detection), `epub_ingestor.py` (ebooklib + BeautifulSoup, TOC + spine walking), `pdf_ingestor.py` (pdfplumber, font-size heuristic for chapter detection). All produce a format-agnostic `RawStory` intermediate with `to_source_md()` that renders canonical markdown for both LLM input and validator reference.
- `llm/` package with an `LLMProvider` ABC (mirrors `TTSBackend`), `AnthropicProvider` (default model `claude-opus-4-5`, reads `ANTHROPIC_API_KEY`), `GeminiProvider` (default `gemini-2.5-pro`, reads `GEMINI_API_KEY`), and `get_provider(name)` factory. Used only by `pipeline/parse.py`; render/QA/package stages remain LLM-free.
- `pipeline/parse.py` — programmatic LLM parse step. Reads `prompts/parse_story.md` as the system prompt, sends `RawStory.to_source_md()` as user input, parses strict JSON, validates via `ScriptModel`, runs `check_faithful_wording`. On divergence, does one targeted retry with the divergence context injected into the follow-up prompt. Caches by `source.md` hash: re-running with unchanged input skips the LLM call. Writes `script.json` + `source.md` into `<build_dir>`.
- `pipeline/epub3.py` — audio-EPUB3 packager. Produces an `.epub` with SMIL Media Overlays ([EPUB 3 spec](https://www.w3.org/TR/epub-33/#sec-media-overlays)) — synchronized text + audio so compatible readers (Apple Books, Thorium, VoiceDream) highlight each paragraph as its audio plays. Reuses per-line WAV durations from `build/ch<NN>/lines/concat.txt` for precise `clipBegin`/`clipEnd` ranges. Cover art registered in manifest + `meta[name=cover]`.
- `pipeline/package.py::package()` — format dispatcher. `format="m4b"` → `build_m4b()`; `format="epub3"` → `pipeline/epub3.py::build_audio_epub3()`. Keeps existing `build_m4b` + CLI intact.
- Cover art embedding in `.m4b` via ffmpeg `attached_pic` disposition — single-pass, no extra dependency. Added `--cover` flag to `pipeline.package` and `pipeline.run`.
- `pipeline/_errors.py` — `PipelineError` base class, `MissingDependency` (carries `package`, `feature`, `install`, `required` fields), `ParseError`, `RenderError`. Optional-dep code paths now raise `MissingDependency` instead of `RuntimeError` so the orchestrator (and the Phase 2 UI) can distinguish "install this" from "something else broke" and take the right action (hard-fail vs graceful skip).
- `pipeline/_logging.py` — `configure_logging(build_dir=...)` sets up a console handler (INFO level, human-friendly with relative timestamps) + a DEBUG-level file handler at `<build_dir>/run.log` with full tracebacks. `pipeline.run` calls it on entry; every stage module uses `logging.getLogger(__name__)`.
- `config.yaml` additions: `output.format` (m4b | epub3), `output.cover_path`, and `llm` block (`provider`, `model`, `max_tokens`).
- `pyproject.toml` new optional-dependency groups: `ingest` (python-docx, pdfplumber, ebooklib, beautifulsoup4), `metadata` (mutagen — reserved for future post-processing), `llm` (anthropic), `llm-gemini` (google-genai). Expanded `ui` group to include `mcp` for Phase 2.
- `llm/` added to `setuptools.packages.find`.

### Changed
- `pipeline/qa.py::whisper_roundtrip` now raises `MissingDependency(required=False)` when `faster-whisper` isn't installed — letting the orchestrator skip Whisper QA without failing the render.
- `pipeline/package.py::build_m4b()` gains `cover_path: Path | None` kwarg; ffmpeg command conditionally maps a cover input as `attached_pic` video stream when supplied.
- `pipeline/validate.py::_normalize` refined for the Phase 1 ingestor's canonical source format: H2+ heading *lines* are dropped entirely (structural chapter markers emitted for multi-chapter stories are JSON metadata, not spoken content), H1 keeps prefix-stripped text (matches the convention where the book title is the narrator's opening line), italic by-lines (`*by Author*`) are dropped. Existing stories' validator behavior unchanged.
- `prompts/parse_story.md` — two clarifications added: (7) book title and preamble paragraph are spoken narrator lines in Chapter 1, include them verbatim so the faithful-wording validator matches; (2, appended) every speaker string in `lines` (including `narrator`) MUST have a matching entry in the top-level `characters` array. Caught on first Gemini end-to-end run where the model treated the title as metadata.
- `pipeline/ingest/base.py::RawStory.to_source_md` no longer emits a redundant `## Chapter 1: <title>` header for single-chapter sources — the H1 title alone suffices and avoids doubling the title in the validator's source reference.
- LLM providers (`AnthropicProvider`, `GeminiProvider`) now raise `ConfigurationError` (not `RuntimeError`) when their API key env var is missing, so the orchestrator distinguishes user-config errors from unexpected crashes. Orchestrator exits 2 for `MissingDependency`, 3 for `ConfigurationError`, 1 for other `PipelineError` / unexpected.

### Added (continued)
- `pipeline/_env.py::load_default_env` — minimal stdlib-only `.env` loader invoked at the top of `pipeline/run.py::main`. Reads `KEY=VALUE` from repo-root `.env`; existing shell env wins; warns on world/group-readable perms. No new dependency.
- `pipeline/_errors.py::ConfigurationError` — distinct exception for missing env vars / bad flag combinations, separate from `MissingDependency` (which is for installed-package issues).
- `.env.example` — template committed to the repo; `.env` is gitignored via new `.gitignore` entries (`.env`, `.env.*`, `*.pem`, `*.key`, with `!.env.example` whitelist).

### Added (pre-existing — leaving in place)
- `pipeline/_memory.py` — memory watchdog module. `require_free(min_gb, backend=...)` checks `psutil.virtual_memory().available` and refuses to start a render/bench with a helpful error when free RAM is below threshold. Catches the "forgot a render was running" case automatically.
- `pipeline/render.py::main()` and `pipeline/bench.py::main()` now call `require_free(4.0)` and `require_free(4.5)` respectively before any model load.
- `psutil>=7.0` added to `pyproject.toml` base dependencies.
- `examples/` directory with three curated `.m4b` samples (P&P Reconciliation, P&P Hunsford, Gatsby West Egg hybrid) and a README explaining what each demonstrates. Linked from the main README's new "Try before you clone" section.
- `BACKLOG.md` entries: supervisor/worker pattern for bulk rendering (with explicit memory-logging requirement), and a companion entry to review those logs and relax the concurrency rules empirically.
- `voice_samples/gatsby_ref.wav` and `voice_samples/daisy_ref.wav` now tracked in git (added `!voice_samples/*.wav` to `.gitignore`). They were overlooked during the hybrid-Chatterbox branch merge because the original gitignore pattern blocked them; without them the repo could not reproduce the hybrid sample.

### Changed
- `CLAUDE.md` rule #1 refined: concurrency is per-backend, not global. Kokoro-only renders can run up to 3 concurrent; any Chatterbox render must be the only one. Whisper QA accounted for explicitly. Rule #2 documents the new watchdog.

### Removed
- *Salt and Rust* artifacts: `stories/salt-and-rust.md`, `cast_salt_and_rust.json`, `build_salt_and_rust/` (32 MB), `samples/cast_salt_and_rust/`, `out/salt_and_rust.m4b/`. Per user directive during cleanup; the project-story narrative in `STORY.md` retains the retrospective record, and `DECISIONS.md` entries #0012–#0015 stay as documentation of the casting reasoning, but the artifacts themselves are gone.
- Old audition sample directories: `samples/cast/` (P&P auditions from early casting iterations), `samples/gatsby_audition/` (Gatsby voice-selection auditions). Superseded once casts were approved.
- Transitive Chatterbox demo-UI packages uninstalled from venv: `pre-commit`, `ffmpy`, `gradio`, `gradio_client`, `fastapi`, `uvicorn`, `starlette`, `safehttpx`, `aiofiles`, `tomlkit`, `orjson`, `semantic-version`, `groovy`, `python-multipart`, `pandas`. Tried removing `onnx` and reverted — `s3tokenizer` needs it. Total venv shrinkage: ~100 MB (1.7 GB → 1.6 GB).
- `.gitignore` entry `stories/salt-and-rust.md` (file is deleted).

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
