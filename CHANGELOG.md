# Changelog

All notable changes to this project will be documented here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — "Easy wins" code review pass: hygiene, quality, speed, UI (2026-04-17)

**Part 1 — Code hygiene**

- **`pipeline/_ffmpeg.py`** — single canonical resolution point for `FFMPEG` / `FFPROBE` binaries (shutil.which + `/opt/homebrew/bin` fallback). Six call sites across `render.py`, `qa.py`, `bench.py`, `package.py`, `_short_line_splitter.py` (×2 inline-in-loop hits) all now import from here. Removes per-call PATH scans inside the VAD loop.
- **`pipeline/_cache.py`** — canonical `line_hash(line, voice_key)` using tuple-string (no `json.dumps` overhead). Shared by both `render.py` and `_short_line_splitter.py`; prevents cache-seat collision if the format ever changes. Replaces the two previously duplicated `_line_hash()` definitions.
- **`pipeline/_tags.py`** — added `@functools.lru_cache(maxsize=256)` to `make_name_tag_regexes`. Previously compiled two regexes per call; called once per character line during split detection. Now compiled once per unique speaker name (20 compilations for a 500-line script vs 500).
- **`tts/__init__.py`** — removed the `xtts` branch; `get_backend("xtts")` now raises `ValueError: Unknown backend ... Known: kokoro, mlx-kokoro, chatterbox`. The old ImportError message falsely listed xtts as "Known".
- **`pyproject.toml`** — removed `xtts = ["TTS"]` optional dependency (was never implemented).
- Import ordering cleanup: `render.py`, `qa.py`, `bench.py`, `package.py` — stdlib imports before business imports, no late-import patterns in module body.

**Part 2 — Output quality**

- **`pipeline/qa.py`** — QA threshold calibration: `PEAK_DB_MAX` relaxed from -1.0 to -0.3 dBFS (loudnorm now targets TP=-1.5; -1.0 was generating false positives). WPS check now skips lines with `<5 words` or `<1500 ms` duration (short attribution tags are legitimately fast; the 1.3 w/s threshold was audiobook-chapter lore, not applicable to 2-word exclamations).
- **`pipeline/_chorus.py`** *(new)* — generic chorus overlay for any line with `line.chorus = True`. Renders `N_base = min(chorus_size, 4)` distinct voice takes; recursively stacks to `min(chorus_size, 8)` with ±2% atempo jitter + 5–80ms adelay + -2 to -6 dB gain per layer. Lead voice at 0 dB/unjittered for intelligibility. ffmpeg `filter_complex` + `amix`. Deterministic (Random seed 42). Gated by `output.chorus_overlay: true` in config.
- **`pipeline/schema.py`** — `LineModel` gains `chorus: bool = False` and `chorus_size: int = 3`; `CastModel` gains `chorus_pools: dict[str, list[str]]` for per-speaker voice pool overrides. Both backward-compatible.
- **`pipeline/_qa_worker.py`** *(new)* — background Whisper QA worker. Single-consumer daemon thread runs faster-whisper `base.en` on each synthesised WAV while MPS samples the next line (CPU-bound + MPS-bound = no contention). Logs low-similarity lines (< 0.70) to `build/<stem>/qa_audit.jsonl`. Wired into `render_chapter`; silently disabled if faster-whisper not installed.
- **`pipeline/cast.py`** — `merge_from_prior(cast, prior_cast_path)` merges matching character entries from a prior project's `cast.json` (case-insensitive name match). CLI: `--cast-from <path>` on `pipeline.cast --propose`.
- **`pipeline/retag.py`** *(new)* — emotion-only LLM re-tagger. Rewrites `line.emotion.*` without touching `line.text`. Re-validates faithful wording post-tag to confirm text bytes unchanged. CLI: `python -m pipeline.retag --script build/<stem>/script.json --chapter N [--dry-run]`.

**Part 3 — Speed infrastructure**

- **`tts/chatterbox_backend.py`** — added `synthesize_raw()` (MPS-only: returns numpy + sr + atempo_ratio) and `postprocess()` (CPU-only: encode + tempo stretch). Splits the synthesis pipeline into two phases for future CPU/MPS overlap pipelining. `synthesize()` delegates to both sequentially (unchanged public API). Added `synthesize_batch()` as a sequential fallback stub — ready for a real batch API if Chatterbox adds one.

**Part 4 — UI enhancements**

- **`pipeline/render.py`** — per-line `ProgressEvent` now includes `extra={"cache_hit": bool, "took_s": float, "speaker": str, "text_preview": str}`. Enables ETA calculation and per-line flicker in the rendering UI.
- **`ui/templates/rendering.html`** — elapsed timer (1s client-side tick), ETA (EMA over last 30 non-cached lines, updated every 5 fresh lines), per-line speaker+text flicker, cache-hit coloring on the progress bar via a second overlay track.
- **`ui/templates/done.html`** — QA audit link: if `qa_audit.jsonl` exists with ≥1 entry, shows a collapsible section with the count and path.
- **`ui/templates/options.html`** — chorus overlay checkbox in new "Audio effects" advanced section; value written to per-build `config.yaml` on submit.
- **`ui/templates/voices.html`** — "Reuse cast from prior project" dropdown (populated via `/api/prior-builds`); upload-your-own reference clip section in the voice picker sheet.
- **`ui/static/app.js`** — `subscribeProgress` accepts `onLineEvent` callback; `initPriorCast` + `initVoiceRefUpload` functions added.
- **`ui/app.py`** — `GET /api/prior-builds` (lists build dirs with cast.json); `POST /api/cast-from/{job_id}` (merges prior cast); `POST /api/voice-reference/{job_id}` (normalizes + registers a custom reference clip). `page_done` computes `qa_audit_count`. `api_options` captures `chorus_overlay` checkbox and writes per-build config.yaml.
- **`ui/services/job_store.py`** — `public_view()` now includes `build_dir` field.

**Part 5 — Tag / identification fixes**

- **`pipeline/normalize.py`** — added `canonicalize_speakers()`. First-seen casing per character becomes canonical; subsequent variant casings are rewritten. Wired into `parse.py` before `split_lumped_dialogue_tags`. Prevents cast.json resolve misses when the LLM emits inconsistent capitalization across chapters.
- **`pipeline/_short_line_splitter.py`** — added module-level `SHORT_LINE_CHAR_THRESHOLD = 10`; default parameter values use it. Named distinctly from `validate.py`'s `main_threshold` (line-count concept). Pre-computes `speaker_backends` dict before the inner loop in both `find_short_line_pairs` and `find_unpaired_short_lines`, removing repeated `cast.resolve()` calls per line. `find_unpaired_short_lines` now calls `find_short_line_pairs` once and reuses result (was calling it twice).

### Added — Part B pipeline productization from Hyperthief session (retro)

- **`pipeline/normalize.py`** — post-parse splitter for lumped dialogue-attribution tags. Handles both `<Name> said` and pronoun (`he said` / `she said` / `they replied`) patterns, sandwiched or trailing. Called inside `pipeline/parse.py::parse_raw_story` right after faithful-wording passes; re-validates post-split as defense-in-depth. Preserves the `" ".join(line.text) == source` contract via per-line invariant check.
- **`pipeline/_tags.py`** — shared tag-detection module. Hoists `_TAG_STARTS` / `_TAG_VERBS` / `text_looks_like_attribution_tag` out of `render.py` so both the normalize step and the pause-gap chooser use the same source of truth.
- **`pipeline/_short_line_splitter.py`** — mitigation for Chatterbox's short-text artifact (GitHub #97: inputs ≤10 chars reliably gibberish). Two strategies: (a) `render_and_split_pair` — pair with adjacent same-speaker line, render combined text, VAD-split on silence; (b) `render_with_appended_tail` — for unpaired short lines, append filler text and VAD-crop. Wired as a pre-synthesis pass in `render_chapter` so the normal per-line loop finds the pre-installed WAVs and cache-hits.
- **`pipeline/_hardware.py`** — hardware snapshot at start + end of render. Records CPU (perf/efficiency split for M-series), RAM, thermal state (`pmset -g therm`), MPS availability, and (end only) peak RSS + wall-clock. Written to `build/<stem>/hardware_{start,end}.json`. Never raises — best-effort.
- **`pipeline/validate.py::check_main_character_voice_uniqueness`** — hard-fail validator. Counts lines per speaker, buckets speakers with ≥ `main_character_threshold` (default 10) by resolved `(backend, voice_id)` tuple, errors on collision. Wired into `render_all` — fails before any synthesis, with an actionable `fix` message.
- **`pipeline/_memory.py::acquire_render_lock`** — fcntl.flock-based lock on `build/.render.lock` (per-build-dir) and `<parent>/.chatterbox.lock` (machine-wide, when Chatterbox is in use). Kernel releases on process exit even on SIGKILL. Wired into `render_all`.
- **Per-line synthesis timing** in `pipeline/render.py::render_chapter`: `time.perf_counter()` around `backend.synthesize()`, logged at INFO level (`ch02 line 23/56: [FM] chatterbox took 4.7s`). Only on cache-miss; re-runs of unchanged lines stay quiet. Grep target: `grep "took" build/<stem>/run.log | sort -rn -k7`.
- **Per-line loudness normalization** in `pipeline/render.py`: ffmpeg `loudnorm=I=-16:TP=-1.5:LRA=11` applied per-line right after synthesis (and right after any resample). Config toggles: `output.loudness_norm` (default true), `output.loudness_target_lufs` (default -16). ~100-200 ms/line overhead.
- **`prompts/parse_story.md`** — rule #2 rewritten from "prefer splitting" to a hard-rule "MUST split". Explicitly covers both `<Name> said` and pronoun patterns with worked examples. Points at the downstream normalizer as a safety net.
- **`config.yaml`** — new keys: `output.inline_tag_pause_ms: 30` (was implicit `base * 0.4 = 72ms` at code level), `output.loudness_norm: true`, `output.loudness_target_lufs: -16`, `output.short_line_mitigation: true`, `output.short_line_threshold: 10`, `output.short_line_max_takes: 3`, `output.short_line_tail`, `validation.main_character_threshold: 10`.

### Fixed — Hyperthief v2.2 rebuild: Chatterbox short-text artifacts via pair-render + VAD-split

- User flagged Rig's "Hey!" at ~50s of v2.1 as completely garbled. Diagnosed as Chatterbox's known short-text artifact (github.com/resemble-ai/chatterbox/issues/97 — 5-char inputs hallucinate; 10 consecutive retries produced wrong phrases with Whisper similarity ≤0.32). Fix: the new `_short_line_splitter` module applied one-off to all 20 short Chatterbox lines in the cached Hyperthief build (18 pair-renders + 2 tail-appends). All 20 installed cleanly; m4b repackaged as v2.2 (20.7 MB, 28:55).

### Fixed — Hyperthief v2.1 rebuild: pronoun-tag splits + loudness normalization

- **Pronoun-based dialogue tags split retroactively.** The v2 render (2026-04-17 15:20 IST) shipped with 8 character-speaker lines still containing embedded `"..." he said` / `"..." she said` attributions — my post-parse split regex had covered `<Name> said` but missed pronoun patterns. User caught this at ~1:42 of listen-through. A one-shot Python script applied the pronoun-regex split to `build/Hyperthief/script.json`: 334 → 348 lines; faithful-wording validator green.
- **Cache realignment via hash-based rename.** The per-chapter `{idx:04d}_{speaker}_{hash}.wav` naming means line insertions shift every subsequent idx. A Python script walked the post-split script, matched each expected `(safe_speaker, hash)` against existing files, and renamed via two-phase `.renaming` suffix (76 renames in ch01, 5 in ch02, 62 in ch03, 30 in ch05). 19 genuinely new split lines cache-missed and got fresh Chatterbox synthesis.
- **Loudness normalization across all 348 cached line WAVs.** Chatterbox clones were rendering -4 to -12 dBFS depending on reference-clip amplitude (LibriVox sources recorded at wildly different levels); Kokoro supports were -10 to -12; narration hit 0 dBFS on some peaks. User heard this as dialogue softer than narration. Applied `ffmpeg loudnorm=I=-16:TP=-1.5:LRA=11` (EBU R128) in-place via tmp-file; 348 files in 36s. Post-norm peaks cluster at -1.5 dBFS (±1 dB).
- **All 6 chapter MP3s re-stitched** from normalized line WAVs; **m4b repackaged** as `out/Hyperthief.m4b` v2.1 — 21.0 MB, 29:12 duration (10s longer than v2 due to added narrator attribution lines). Cover art + title/artist tags + chapter markers preserved.

### Added — `output.inline_tag_pause_ms` config + smarter dialogue-tag detection in `pipeline/render.py`

- `output.inline_tag_pause_ms` (int, ms) — new optional config override for the silence gap around a narrator attribution tag (`[Rig dialogue] → [narrator "Rig said,"] → [Rig dialogue]` after splitting a lumped tag line). Read from per-story or global `config.yaml`. Defaults to `int(line_pause_ms * 0.4)` (= 72 ms at default base 180) so existing stories render identically. Per-story override lives in `build/<stem>/config.yaml`; `pipeline/config.py::load_config` already deep-merges it over global.
- `_text_looks_like_attribution_tag()` — new helper that recognizes narrator lines as dialogue tags via three cues: short length (≤30 chars), a `_TAG_STARTS` prefix (`he said`/`she said`/…), or a `<SpeakerName> <tag_verb>` match. The speaker-name case catches splits like `FM said.` / `Jesna asked.` which the old ≤30-char fallback caught only by length coincidence, not intent.
- `_is_inline_tag()` now delegates to the helper; the `_TAG_STARTS` length threshold bumped from ≤60 to ≤80 to accommodate action-beat tags (`"FM said, pulling on Rig's hand."` = 32 chars, just over the old fallback). Contract otherwise unchanged — sandwiched same-speaker dialogue still required.
- `_is_trailing_tag()` — **new**. Detects paragraph-final attribution (`[FM dialogue] → [narrator "FM said."]` where the next line crosses a paragraph boundary). Tight pause applies only to the BEFORE side; the AFTER pause falls through to standard speaker-change/paragraph logic since the tag ends the paragraph. Without this, trailing splits got a ~400 ms gap before the tag, reading as an unnatural pre-attribution pause.
- Hyperthief-specific override: `build/Hyperthief/config.yaml` sets `inline_tag_pause_ms: 10` — user's preferred tightness for this render. Global behavior unchanged.
- `re` added to `pipeline/render.py` imports for the speaker-name pattern matcher.

### Added — combined mode: web UI + MCP server in one process; "Use my Claude app" provider now works

- `pipeline/serve.py --mode combined` boots a single uvicorn process that serves the web UI on `/` and an MCP server on `/mcp/sse` + `/mcp/messages/`. Third mode alongside `ui` (web UI only, no MCP) and `mcp` (stdio, for Claude-Code-spawned subprocess use). All three are independent; pick one per launch.
- `pipeline/mcp_server.py::build_server()` — factored out from the stdio entry point so the HTTP/SSE mount can reuse the same 5 tool definitions. `run_stdio()` now calls it; nothing duplicated.
- `ui/mcp_mount.py` — **new file**. Mounts `SseServerTransport` onto the FastAPI app, handles SSE lifecycle via `server.run()`-equivalent body, captures the live `ServerSession` into a module-global so outside code can reach it for sampling. Exposes `get_current_session()`, `get_current_loop()`, `is_attached()`.
- `llm/mcp_sampling_provider.py` — stub replaced with a real implementation. `complete(system, user, ...)` looks up the captured session + event loop, bridges to the async `ServerSession.create_message()` via `asyncio.run_coroutine_threadsafe`, extracts text from the response, returns a string compatible with every other `LLMProvider`. Handles timeout, `McpError` (disconnected client, sampling unsupported), and generic exceptions — all become `ConfigurationError` with actionable fix instructions per the user's hard-fail preference.
- `ui/app.py` lifespan now honors `AMW_MCP_COMBINED=1` (set by the combined-mode launcher) and calls `ui.mcp_mount.attach(app)` during startup. Absent the env var, the app runs without the MCP routes (standard `--mode ui` behavior).
- `ui/templates/settings.html` — "Use my Claude app" radio option now has the full setup instructions inline: the `--mode combined` command + the exact `~/.claude/settings.json` JSON block users paste.
- `README.md` — new "Use Claude as the LLM — no API key" section.
- `ui/static/style.css` — `pre.inline-code` rule for the Claude-config snippet in settings.

### Behavior — hard-fail when no Claude client connected (per user's explicit choice)

- Selecting "Use my Claude app" in Settings and uploading a book when no Claude client is connected: parse stage fails with a clear `ConfigurationError` message containing both the `--mode combined` launch command and the Claude config JSON. No silent fallback to Anthropic/Gemini. Job is marked resumable on the history page so the user can retry after connecting their client.
- Mid-parse disconnect: `McpError` is re-raised as `ConfigurationError` with "your Claude client may have disconnected" guidance.

### Added — split voice engines (narrator vs characters) + MCP default provider

- `ui/services/settings.py::Settings` gets `narrator_backend` and `character_backend` fields (defaults `mlx-kokoro` and `chatterbox` respectively). The original `backend` field is kept as a single-engine fallback, rarely touched. Default provider changed from `anthropic` to `mcp` — most users who install this have a Claude client connected.
- `ui/services/job_store.py::PersistedJob` gets the same two fields so every job records which engine rendered which role. Empty string = "fall back to `backend`" for backward-compat with old job files.
- `pipeline/cast.py::propose` gains a hybrid mode. When `narrator_backend` and `character_backend` are both supplied and differ, the `narrator` speaker is cast from the narrator backend's voice list and every other character from the character backend's — producing a `CastModel` where each entry is a `CastEntry(voice=..., backend=...)` so the existing per-line render dispatcher routes correctly. Single-engine mode unchanged; old cast.json files still load.
- Optional `narrator_backend_obj` / `character_backend_obj` kwargs let the UI pass pre-loaded backend instances from its shared pool so MLX / Chatterbox aren't loaded twice per process (same pattern as the existing single-backend kwarg).
- `ui/app.py::_start_parse` chooses hybrid vs single-engine propose based on whether `job.narrator_backend != job.character_backend`; `_start_render` preloads both engines into the render seed dict.
- `/api/settings` and `/api/options/<id>` accept `narrator_backend` + `character_backend` form fields.

### UI

- Settings page: two dropdowns — "Narrator voice engine" (restrained is right by default for narrators) + "Character voice engine" (expressive/voice-cloning is right by default for characters). Original single-engine knob moved into an "Advanced — fallback engine" disclosure.
- Options page: same split, with a "Fallback (when narrator = characters)" disclosure for the single-engine case.
- Home page quick-settings chip: when the two engines differ, shows both with `(narrator)` / `(characters)` labels. Collapses to one label when they're the same.

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
