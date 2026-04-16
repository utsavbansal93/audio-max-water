# Decisions

Lightweight ADR log. Format per entry: **Context / Options / Decision / Consequences**. Short, numbered, dated.

---

## 0001 · 2026-04-16 · Default TTS backend: Kokoro

**Context.** The pipeline needs a TTS engine that runs on M3 MacBook Air (16 GB), costs nothing, produces distinct voices per character, and stays consistent across chapters. Zero-touch preferred (no reference-clip sourcing).

**Options considered.**
- **Kokoro TTS** (StyleTTS2, 82M, non-autoregressive): 54 preset voices, deterministic, tiny, fast on CPU.
- **Chatterbox** (Llama-0.5B backbone, autoregressive): voice cloning, best-in-class emotion slider, needs reference clips.
- **XTTS v2** (Coqui, GPT-style): voice cloning, Coqui is unmaintained.
- **Edge-TTS** (cloud): rejected per user (wants AI models, not rule-based/cloud).

**Decision.** Kokoro is the default. Chatterbox is built into the swappable interface as an optional upgrade for emotion-heavy chapters.

**Consequences.**
- Zero setup cost per character — pick a preset voice id and go.
- Emotion is implicit (punctuation-driven), so we encode emotional context in the prose around each line when possible. The `emotion` field in `script.json` is still populated for forward-compat; Kokoro ignores it, Chatterbox uses it.
- If we later find Kokoro's emotion flat for climactic scenes, swap to Chatterbox for that chapter only. Voice identity shifts slightly (Kokoro preset vs cloned reference), so the cast rendered under Kokoro can't be trivially continued under Chatterbox — this is a real limitation worth remembering.

---

## 0002 · 2026-04-16 · `cast.json` is the authoritative voice map

**Context.** Actor-to-character consistency must hold across chapters. If Opus re-casts on every chapter, voices drift.

**Options considered.**
- Re-cast every chapter (simple, but drifts).
- Cache cast in `script.json` (couples casting to parsing).
- Separate `cast.json`, immutable unless explicit swap.

**Decision.** Separate `cast.json`, versioned, only mutated by `pipeline/cast.py` `--swap` / `--approve`. Never regenerated implicitly.

**Consequences.**
- Adding a new character in a later chapter: `cast.py --propose` only proposes for *new* names; existing mappings are untouched.
- Validator refuses to render if any script speaker is missing from `cast.json`.

---

## 0003 · 2026-04-16 · Per-line WAVs retained after stitching

**Context.** Bad lines happen — mispronunciations, wrong emotion. Re-rendering the entire chapter wastes minutes.

**Decision.** `render.py` keeps `build/ch<NN>/lines/NNNN_<speaker>.wav` even after stitching. A line is only re-synthesized if its `text`, `speaker`, `emotion`, or `voice_id` changed (hash-compared).

**Consequences.** Tens of MB per chapter of extra disk. Surgical re-renders. Enables a future `--fix-line 42` command.

---

## 0004 · 2026-04-16 · Swappable backend via ABC, not plugin system

**Context.** We want to swap TTS engines without touching pipeline code. Full plugin systems (entry-points, dynamic discovery) are overkill for 2–3 engines.

**Decision.** Plain ABC in `tts/backend.py`, factory `get_backend(name)` with a hardcoded dispatch. Adding an engine = one file + one line in the factory.

**Consequences.** Trivial to extend; no packaging overhead. The ABC's `Emotion` dataclass is a *superset* — engines silently ignore unsupported fields, so pipeline data structures never fork per engine.

---

## 0005 · 2026-04-16 · Inline dialogue-tag detection for pause logic

**Context.** After tuning emotion-aware pauses, user heard "once or twice awkward narrator pauses." Diagnosis: a narrator line that's actually a dialogue tag ("he replied," between two Darcy lines) was getting the full 2.2× speaker-change gap on both sides, so the tag sounded detached from the dialogue it attributes.

**Options considered.**
- Make tags shorter inside the script (e.g., glue Darcy's opening to "he replied," as one line via text tricks) — breaks faithful-wording.
- Move pause decisions to prompt time (Opus emits `pause_before_ms`) — leaks prosody concerns into the parsing layer.
- Detect inline tags in the renderer from structural signals (short, narrator, sandwiched between same-speaker dialogue, starts with a known tag phrase).

**Decision.** Structural detection in `pipeline/render.py::_is_inline_tag`. Tags get 0.4× base gap on both sides; non-tag narrator-to-narrator gets 1.2× base (room for prose sentences); same-speaker dialogue fragments get 0.9× base (flowing rhetoric).

**Consequences.** Fixes the awkwardness without touching the script or the backend. The detector is heuristic (short + sandwiched + tag-starts) — may miss exotic tags. Monitoring: if QA flags a short narrator line with unusual RMS, that's often a misclassified tag.

---

## 0006 · 2026-04-16 · Pronunciation normalize inside Kokoro backend, not script

**Context.** QA caught "Lydia/Wickham" being spoken as "Lydia slash Wickham" by Kokoro. Fix location is a trade-off: the script preserves source text faithfully; the engine reads it literally.

**Options considered.**
- Change `script.json` text to "Lydia and Wickham" — fails faithful-wording validator.
- Add a preprocessing hook in the pipeline between script and backend — another pipeline step to maintain.
- Put normalization inside the Kokoro backend (`_pronounce`).

**Decision.** Pronunciation is a rendering concern; put `_pronounce()` inside `tts/kokoro_backend.py`. Each backend can have its own (Chatterbox may not need one; Sesame may need more). Script text stays byte-verbatim.

**Consequences.** Backends drift in how they handle odd symbols, but that's correct — each engine has different literal-reading quirks. If we switch backends we may need to tune the normalizer per engine.

---

## 0007 · 2026-04-16 · Automated QA + Whisper round-trip before human review

**Context.** Only the user can judge "does it sound good," but many failure modes are cheap to detect mechanically. Running objective QA first reduces the cost of each human listen.

**Options considered.**
- Pass rendered audio to a multimodal LLM (Gemini 2.5) for "does this sound natural" — blocked by Claude Code not having audio input and the added cost of API-based eval.
- Signal-processing checks only (duration, peak, RMS, pacing) — catches gross defects but not mispronunciations.
- Signal-processing + Whisper round-trip — transcribes audio back to text, diffs against script. Catches dropped words, literal mispronunciations, slash-as-"slash" bugs.

**Decision.** Add `pipeline/qa.py` with signal-processing checks + optional Whisper round-trip via `faster-whisper` (base.en, local, int8). Multimodal AI listening is a future follow-up if needed.

**Consequences.** Non-zero render time overhead for Whisper (~4-6 s for a 1.5-min chapter on M3 CPU). Value: the "slash" bug was caught mechanically on first run. Decision to escalate to a full LLM listener is deferred until Whisper-catchable defects stop being the limiting factor.

---

## 0008 · 2026-04-16 · TTS research findings — backends to add later

**Context.** Initial TTS selection (Kokoro / Chatterbox / XTTS) was from training knowledge, not current research. Web search in this session surfaced several 2025–2026 models that weren't in the original comparison.

**Findings.**
- **MLX-Audio** (Blaizzy/mlx-audio): runs Kokoro natively on Apple Silicon's Neural Engine / GPU via MLX. ~2-3× faster inference than our current torch path. Same model weights.
- **Sesame CSM** (1B, Llama-based, from Sesame Labs): specifically designed for multi-speaker conversational speech. Best-in-class for non-verbal cues and subtle tones. Directly relevant to our full-cast use case.
- **F5-TTS**: "most well-rounded" per 2026 speech benchmarks; strong voice cloning.
- **Chatterbox-Turbo**: 350M params, single-step diffusion — much faster than the version originally planned.
- **Dia** (Nari Labs): supports inline non-verbal tags `(sighs)`, `(whispers)`, `(laughs)` — natural fit for our `Emotion.notes` field.
- **Prior art**: `chatterbox-Audiobook`, `local-tts-studio`, `epub2tts` already exist for audiobook generation. Worth mining for pause/chunking patterns.

**Decision.** Keep Kokoro as the current default (Kokoro is good enough for the current scene per user review). Add backends in order of expected payoff under the same `TTSBackend` ABC:
1. **mlx-kokoro** (free speedup, same output quality) — next.
2. **sesame-csm** (expected bigger emotional range for multi-speaker) — when Kokoro's ceiling is hit.
3. **dia** (non-verbal cue support) — when stylized emotional moments need explicit "(sigh)" tags.
4. **chatterbox-turbo** / **f5-tts** (voice cloning path) — only if user wants specific voices sourced from real-actor samples.

**Consequences.** We were moving without knowing what we were missing. Correcting that now via research and adding one at a time, each behind the swappable backend interface so we can A/B without pipeline changes.

**Retrospective lesson.** Always run the tool-search / web-search step *before* committing to a primary dependency. "Going from training knowledge" is a cheap-looking choice that accumulates as invisible tech debt.

---

## 0009 · 2026-04-16 · MLX-Kokoro as the new default backend

**Context.** `DECISIONS.md #0008` identified MLX-Audio as the expected cheap speedup on M3. First implementation actually ran 2× slower than the torch path (RTF 0.47 vs 0.21) — because `mlx_audio.tts.generate.generate_audio` calls `load_model(model_path=<string>)` on every invocation when you pass the repo-id. We were re-loading the 82M model per line.

**Options considered.**
- Accept the slowdown (MLX still gave cleaner Whisper round-trip 0.989 vs 0.973) — worse performance for slightly better faithfulness is a bad trade.
- Replace `generate_audio` with a direct pipeline wrapper — more code to maintain.
- Load the model once in `MLXKokoroBackend.__init__` and pass the instance to `generate_audio` — the function accepts both strings and `nn.Module` instances.

**Decision.** Load once in `__init__`, pass instance. Result: RTF dropped to 0.15 (vs torch 0.21) on the Reconciliation scene and 0.19 (vs torch 0.23) on Hunsford. ~27% speedup. Same QA pass rate. Whisper similarity higher on both scenes (0.989 / 0.992 vs 0.973 / 0.986).

**Consequences.**
- `config.yaml` default is now `mlx-kokoro`; torch `kokoro` remains as a swappable backend.
- The `cast.json` produced under `kokoro` is reused as-is (same voice IDs, same weights) — the render resolution order now explicitly treats `cast.backend` as informational.
- Retrospective lesson: *first implementation of a new backend is almost always held back by a default that doesn't fit batched use*. Always inspect the inference entry point for per-call allocation / loading before trusting benchmarks.

---

## 0010 · 2026-04-16 · Per-book cast files + script-format source support

**Context.** User submitted a Great Gatsby scene — different book, different character set (Nick, Gatsby, Daisy), different accent (American), and in *script format* rather than prose (`Narrator:` / `Gatsby:` speaker labels, `(stage direction)` parentheticals before dialogue). The existing `cast.json` was hard-wired to P&P's characters; the validator was built for prose sources.

**Options considered.**
- One global `cast.json` with all characters across all books — short-term simple, but breaks the one-voice-per-character contract because `narrator` would collide (the voice for P&P's narrator is not the voice for Nick Carraway).
- Nested `cast.json` keyed by book — requires schema version bump and a way to select the book at render time.
- Per-book `cast_<book>.json` files at repo root; select via `--cast` flag on pipeline commands.

**Decision.** Per-book cast files. `cast.json` stays as the default (P&P), `cast_gatsby.json` joins it. Simple, no schema churn, and the voice-consistency contract now holds *per book* — which is what it should have been from the start.

**Separately on script-format sources.** Extended `pipeline/validate.py::_normalize` with two rules:
- Strip line-start speaker labels matching `^\s*[A-Z][A-Za-z]+:\s*` (handles `Narrator:`, `Gatsby:`, `Mr. Darcy:`, etc.).
- Strip all `(…)` parentheticals — they're treated as stage directions that feed `emotion.notes` in `script.json` rather than being spoken.

The stage-direction-to-emotion mapping is where the format earns its keep: the user wrote `(In a hollow, automatic voice)` before Gatsby's "Five years next November," and I transcribed that directly into the line's `emotion.notes` — the LLM parser (me) already had explicit direction, no guessing required. When prose-form sources are given (Austen), `emotion.notes` is authored from book context instead.

**Consequences.**
- Two source formats supported: prose and script. Both validate. The script format is clearly easier for user-authored content where they want to *direct* the actor — worth mentioning as a recommended format in README.
- The parenthetical-stripping rule is aggressive — prose with genuine parenthetical content (e.g., "he said (for the third time) that…") would lose it in validation. Not a problem today but a watch-item. If we hit it, we switch to stripping only parentheticals that sit adjacent to speaker labels.
- Per-book casts are independent; voice drift across books is expected and correct (Nick sounds different from Austen's narrator; he should).

---

## 0011 · 2026-04-16 · Kokoro's emotional ceiling; Option D (hybrid engine) selected

**Context.** Three scenes rendered and listened-to: P&P Reconciliation (British voices, validated), P&P Hunsford (British voices, validated), Gatsby West Egg Reunion (American voices). User reported Gatsby's Gatsby + Daisy (`am_onyx`, `af_heart`) sounded "very AI and flat" — the narrator voice (`am_michael`) was fine. Iteration 7 ("drama amp") widened the pace coefficient, doubled intensity deceleration, added drama-punctuation trails, doubled held-breath silences on peaks, and pushed intensity values in the script to 0.95–1.0. User confirmed: the changes did not produce emotion. Reverted in commit `b852045`.

**Root cause.** Kokoro is non-autoregressive (StyleTTS2-style). It accepts text + speed, nothing else. There is no "emotional state" input, no slider, no reference-audio prompt. Any emotional variation heard in Kokoro output is a side-effect of punctuation and speed — essentially reading quirks, not acted emotion. Kokoro's British presets happen to have more native pitch range than the American presets, which is why the Austen scenes landed. The American voices hit the ceiling first, but the ceiling is there for every Kokoro voice eventually. **Structural prosody (silence, pace, contrast) can imply emotional state but cannot make a voice sound emotional** — that's an autoregressive-TTS job.

**Options reconsidered.**
- Exhaust more Kokoro tuning — ruled out by iteration 7 outcome.
- **Chatterbox** (Resemble AI, Llama-0.5B backbone, autoregressive) — explicit `exaggeration` slider per-line, voice cloning from 5–10 s reference clips, runs on MPS.
- **Sesame CSM** (1B, Llama-backbone) — best-in-class for multi-speaker / non-verbal cues per 2026 benchmarks, also reference-based. Larger, slower, more unknowns.
- **Dia** (Nari Labs) — inline emotion tags in text (`(sighs)`, `(whispers)`). Different workflow; less battle-tested.
- **Full swap to any of these** — loses Kokoro's speed + determinism for the narrator lines which are already good.
- **Hybrid per-speaker backend assignment** — keep Kokoro where it works (narrators + British voices), swap to Chatterbox where it doesn't (emotional American characters).

**Decision.** Hybrid (Option D). Kokoro for narrator voices; Chatterbox for emotional characters. Reference clips sourced from LibriVox public-domain audiobook readings (Great Gatsby entered US PD Jan 2021; P&P always). Implementation happens on a separate branch (`claude/hybrid-chatterbox`) via a worktree so main stays clean.

**Consequences.**
- Cast schema extends from `{character: voice_id}` to `{character: {voice, backend}}` with backward-compat (bare strings keep resolving to the cast's default backend).
- Per-speaker backend resolution in `pipeline/render.py`: load each needed backend once, dispatch per line. Existing `MLXKokoroBackend.__init__` pattern (hoist model load out of per-call path) reused.
- `Emotion.intensity` finally maps to something real (Chatterbox's `exaggeration` slider). The Emotion dataclass was always designed as a superset — engines silently ignore what they can't do. Chatterbox finally uses the full shape.
- Future path open: Sesame CSM is a drop-in addition under the same ABC when/if Chatterbox hits a ceiling of its own.

**Retrospective lesson.** *Before tuning a component, know its inputs.* I spent an iteration tuning prosody around Kokoro before re-reading its architecture note — if I had re-read earlier, I would have stopped at "Kokoro takes text + speed, nothing else" and escalated to Chatterbox immediately. The rule to internalize: *when a component's output lacks a property, check whether the component has an input for that property before trying to compensate around it.*

---

## 0012 · 2026-04-16 · Per-story config override via `<build_dir>/config.yaml`

**Context.** Production notes for *Salt and Rust* specified 2–3 second pauses at `---` section breaks. Global `config.yaml` had `scene_pause_ms: 1200` (1.2s). Mutating the global config file would silently affect all other stories rendered while the value is different.

**Options considered.**
- **Mutate global `config.yaml`**: simple, but affects all stories; easy to forget to revert.
- **CLI flag `--story-config`**: explicit, but requires all pipeline scripts to accept and thread the argument.
- **Auto-detect `<build_dir>/config.yaml` and deep-merge**: zero CLI change needed; each story carries its own exceptions; global config remains the authoritative default.

**Decision.** Auto-detect and deep-merge. Added `pipeline/config.py::load_config(build_dir)`. `render_all` calls it after resolving `build_dir`, updates module-level `CFG`. Per-story config files are shallow — only keys that differ from global need to appear.

**Consequences.**
- Each story can tune pause timing, backend, sample rate independently.
- The merge is deep (nested dicts merged, not replaced), so a story can override `output.scene_pause_ms` without repeating the entire `output` block.
- Any pipeline script that doesn't call `load_config` won't see the per-story override — currently only `render.py` is updated; `cast.py` and `package.py` don't use timing config so this is fine.

---

## 0013 · 2026-04-16 · *Salt and Rust* narrator voice: `bm_george`

**Context.** Production notes: "lower register, weathered, dry, age-ambiguous, unhurried. Reference: Holter Graham on McCarthy, Tom Hardy on Aesop's Fables." Two British male narrator-tagged voices available: `bm_george` (mature / authoritative / literary / narrator) and `bm_fable` (measured / narrator).

**Options considered.**
- **`bm_george`**: mature age class; "authoritative" and "literary" tags.
- **`bm_fable`**: adult age class; "measured" tag — suggests calm, even delivery.

**Decision.** `bm_george`. "Mature" age class better fits "age-ambiguous but has seen things." "Authoritative" is closer to the McCarthy-reader register than "measured" — measured implies calibration, authoritative implies weight.

**Consequences.** If `bm_george` reads too heavy or sonorous for the flat clinical tone, `bm_fable` is the swap candidate.

---

## 0014 · 2026-04-16 · *Salt and Rust* Furiosa voice: `af_nicole`

**Context.** Production notes: "female, low alto, late 30s–40s, clipped, never warm, dry. Australian inflection welcome but not required — if the actor can't land it cleanly, drop it." No Kokoro preset has an Australian accent.

**Options considered.**
- **`af_nicole`**: adult, tagged "cool / composed / dry."
- **`af_river`**: adult, tagged "calm / steady."
- Australian accent: not available in Kokoro; production notes explicitly provide a fallback ("neutral hard-consonant delivery works equally well").

**Decision.** `af_nicole`. The "dry" tag is the decisive match — production notes use that exact word repeatedly. "Calm/steady" (`af_river`) implies a groundedness that edges toward warmth; Furiosa explicitly doesn't have warmth.

**Consequences.** If `af_nicole` reads too cool/professional rather than clipped-wasteland, `af_river` is the swap. Australian accent remains unachievable in Kokoro; Chatterbox voice cloning could approximate it with a reference clip if ever prioritized.

---

## 0015 · 2026-04-16 · *Salt and Rust* Mariner voice: `am_echo`

**Context.** Production notes: "no accent — he is from nowhere now. Not gruff, not mysterious on purpose. Plain, not opaque." Candidates: `am_echo` (neutral / clear), `am_eric` (grounded), `am_adam` (everyman).

**Options considered.**
- **`am_echo`**: neutral / clear — blank instrument.
- **`am_eric`**: grounded — risk of earthy, character-voice affect.
- **`am_adam`**: everyman — generic; potentially the most "actor-voice" of the three.

**Decision.** `am_echo`. "Neutral/clear" is the closest tag approximation to "from nowhere, plain not opaque." The production note's strongest direction is negative: *not* mysterious, *not* gruff, *not* theatrical. `am_echo` is the most subtractive voice in the catalog.

**Consequences.** If `am_echo` reads too thin or flat to differentiate from dead air, `am_eric` (grounded) is the next swap. The Mariner is the hardest voice to cast precisely because the direction is defined by what it must *not* be.

---

## 0016 · 2026-04-16 · Cast schema: `str | CastEntry` with backward-compat

**Context.** Option D (Kokoro narrator + Chatterbox characters) needs per-character backend assignment. The prior schema was `dict[str, str]`.

**Options considered.**
- New shape, break legacy: `dict[str, CastEntry]`. Forces rewriting every existing cast.json. Simple code, breaks change.
- Union shape, keep legacy readable: `dict[str, str | CastEntry]` with a `resolve()` helper that applies the `str → CastEntry(voice=s, backend=cast.backend)` shim at access time.
- Parallel `extended_mapping` dict: additive, ugly, two places to look.

**Decision.** Union shape + `resolve()`. All existing P&P casts keep parsing unchanged; only Gatsby's cast file uses the expanded form.

**Consequences.**
- `cast.resolve(speaker)` is the single entry point for reading the mapping. `pipeline/render.py::render_chapter` uses it; direct reads of `cast.mapping[speaker]` (legacy style) would skip the shim and see raw `str | CastEntry` — one place did this in the old `check_voice_consistency`; the new `render_all` validator uses `resolve()`.
- When the user eventually migrates everything to the expanded form, the `str` branch becomes dead code, removable in one PR with no runtime change.

---

## 0017 · 2026-04-16 · LibriVox Dramatic Reading for reference clips

**Context.** Chatterbox needs 5–15s single-voice reference clips per character. Options for sourcing vary in cost and quality.

**Options considered.**
- **Self-recorded** — impossible in this environment (no mic access) and would miss the "character-appropriate" acting quality anyway.
- **Bundled Chatterbox example voices** — not character-specific; sanity-check only.
- **Kokoro-seeded** — generate Kokoro output, clone from it. Circular and inherits Kokoro's flatness. Useless for our problem.
- **LibriVox solo reading** — one reader voices all characters; their "Gatsby" is still their own voice with acting, not a distinct timbre. Better than Kokoro-seeded, not great.
- **LibriVox Dramatic Reading** — different readers per role. LibriVox v5 of *The Great Gatsby* is exactly this: Tomas Peter as Gatsby, Jasmin Salma as Daisy, TJ Burns as Nick. Real acted performances by different people, PD, free.

**Decision.** LibriVox Dramatic Reading. Chapter 5 has both Gatsby and Daisy speaking the scenes they need to. Extracted 7.9s / 9.3s clips using `faster-whisper` word-level alignment against our known script lines.

**Consequences.**
- Each character voice is now rooted in a real actor's performance, amplified by Chatterbox's `exaggeration` slider for the specific line-level emotion we want.
- Licensing trail is clean (both text and recording are PD; attribution logged in `voice_samples/SOURCES.md` for audit).
- Future characters from other PD-audiobooked works are sourceable by the same pattern. Characters from works not in PD (or without dramatic readings) need a different sourcing strategy — we don't have one yet; flag this when it comes up.

---

## 0018 · 2026-04-16 · Hard-exit on Chatterbox shutdown to suppress macOS crash dialog

**Context.** After loading Chatterbox, normal Python interpreter shutdown triggers SIGBUS inside `_sentencepiece.cpython-312-darwin.so` (KERN_PROTECTION_FAILURE). The work has already completed; this is a destructor-path bug in the native module under the torch 2.6 + numpy 1.26 stack Chatterbox forces. macOS surfaces it as a "Python quit unexpectedly" dialog. User flagged this as alarming.

**Options considered.**
- **Downgrade sentencepiece** to an older wheel — lots of compat risk with transformers/tokenizers.
- **Patch sentencepiece from source** — time-expensive and fragile.
- **Register `atexit(os._exit(0))`** in the Chatterbox backend's `__init__` — skips Python's normal shutdown (including the broken destructor) and exits the process hard. Work is already done by the time atexit runs.
- **Ignore** — user-facing dialog is bad UX, not acceptable.

**Decision.** `install_clean_exit_hook()` in `tts/chatterbox_backend.py`, called from `ChatterboxBackend.__init__` before the model load. Only processes that actually load Chatterbox get the hard-exit behavior; Kokoro-only runs keep normal Python shutdown.

**Consequences.**
- No more crash dialog after Chatterbox renders.
- `os._exit(0)` skips any user-registered atexit handlers or module finalizers. Current pipeline doesn't rely on those, but anyone adding background-thread cleanup or telemetry-flush hooks needs to know they'll be skipped in Chatterbox-using processes.
- If sentencepiece ships a fix upstream, this hook becomes dead code — removable with a one-line revert. Flagged for periodic re-check.

---

## 0019 · 2026-04-16 · Chatterbox pace via ffmpeg post-processing

**Context.** Chatterbox has `exaggeration`, `cfg_weight`, `temperature`, but no native speed/pace parameter. The Emotion dataclass's `pace` field has no direct target.

**Options considered.**
- **Skip pace on Chatterbox** — Emotion.pace silently ignored. Cross-engine behavior diverges: a line with `pace: -0.3` would slow under Kokoro and render at default under Chatterbox.
- **Tempo-stretch the generated WAV via ffmpeg `atempo`** — industry-standard time stretching without pitch change. One ffmpeg invocation per line.
- **Re-generate at altered Chatterbox parameters** — `temperature` and `cfg_weight` affect prosody but unpredictably; not a real pace knob.

**Decision.** ffmpeg `atempo` post-processing. Same 0.40 coefficient family as the Kokoro backend (see kokoro_backend.py) so `Emotion.pace` is meaningful and roughly-comparable across engines. Pace ratios near 1.0 skip the ffmpeg step to save a process spawn.

**Consequences.**
- Small quality cost for extreme pace values (atempo introduces mild artifacts > 15% stretch), but our pace range is ±30% so it's within atempo's clean zone.
- One extra ffmpeg call per non-default-pace Chatterbox line — negligible overhead vs Chatterbox's diffusion sampling cost.
- Keeps engine-specific machinery inside `chatterbox_backend.py` — pipeline stays engine-agnostic.

---

## 0020 · 2026-04-16 · Per-backend memory budget + `require_free` watchdog (not global serialization)

**Context.** The 20 GB SSD-swap incident during a hybrid render forced a memory rule. First-pass rule was "never run more than one render process at a time." User pushed back: over-restrictive. Three Kokoro renders together consume ~1.5 GB and are trivially safe; the real problem was stacking Chatterbox + Whisper + MLX-Kokoro in one process while browsers and OS ate the rest of 16 GB.

**Options considered.**
- **Keep "one render at a time" globally.** Simple, crisp, over-restrictive for Kokoro work. User rejected.
- **Per-backend budget in docs only (no enforcement).** Describe Kokoro = up to 3, Chatterbox = exactly 1. Easy to document; relies entirely on human discipline.
- **Enforced per-backend via process coordination** (pid/lockfile tracking). More robust but requires tracking "which render is running," handling zombies, coordinating across terminal tabs. Infrastructure tax.
- **Free-RAM watchdog at render startup.** Check `psutil.virtual_memory().available` before any model loads; refuse with a clear error if below threshold. No cross-process coordination — just look at what the machine actually has right now.
- **Full supervisor/worker pattern.** One long-lived process holds models, workers dispatch requests. The correct long-term shape but ~1–2 sessions of infrastructure work to build and debug; premature for current one-scene-at-a-time workflow.

**Decision.** Combine the documentation option and the free-RAM watchdog. `CLAUDE.md` rule #1 now describes the per-backend budget (Kokoro ≤ 3 concurrent, Chatterbox = 1). `pipeline/_memory.py::require_free(min_gb, backend=...)` runs at the top of `pipeline/render.py::main()` and `pipeline/bench.py::main()`; refuses to start if free RAM is below 4 GB (render) or 4.5 GB (bench, which also loads Whisper). Supervisor pattern filed in `BACKLOG.md` as the right long-term direction with an explicit requirement to log per-request RSS stats so we can empirically relax the rule once data exists.

**Consequences.**
- Catches the common failure mode (forgot a render was running, started another) without needing cross-process machinery. The watchdog message points at the fix (close apps / kill python procs / smaller scope).
- Doesn't catch mid-render memory growth — if a render pushes into swap partway through, current behavior stands (macOS swaps; painful but not catastrophic). Acceptable per Phase 5 of the plan.
- The 4.0 / 4.5 GB thresholds are slightly conservative (OS + single model set typically needs 3 GB). Set a little high to cover the case where other apps grow during the render. Can be tuned down once the supervisor logs real distribution data.
- Introduces a runtime dep on `psutil>=7.0`; small (~1 MB installed), no native compile needed.

**Retrospective lesson.** *Prefer observation-based enforcement over static rules where cheap.* The watchdog checks actual conditions at runtime instead of asserting what should be true in general. That's both more robust (catches situations the rule-author didn't imagine) and self-documenting (the error message teaches the rule). When this kind of instrument is cheap to build — here, 50 LOC and one library — prefer it to rules humans have to remember.

---

## 0021 · 2026-04-16 · `pipeline.run` orchestrator replaces the manual Claude-in-loop parse step

**Context.** Until now, the pipeline required a human to drive the parse step: copy the story into a Claude chat, paste the system prompt from `prompts/parse_story.md`, wait, paste the JSON output into `build/script.json`, then run the deterministic stages (cast / render / qa / package). User wanted a single-command end-to-end flow that works without Claude Code sitting in the loop — both so they can ship this to others and so they (via Claude Code) can orchestrate an entire book without the paste ceremony.

**Options considered.**
- **Thin CLI wrapper that calls `pipeline.bench` after a manual parse** — doesn't solve the problem; parsing is still manual.
- **Callable Claude via `claude_agent_sdk`** — would work, but locks the project into Anthropic's tooling. User explicitly asked for Anthropic OR Gemini support.
- **Programmatic LLM call via provider-specific SDKs (Anthropic / Gemini) abstracted behind an `LLMProvider` ABC.** Orchestrator (`pipeline.run`) calls the provider with the existing `parse_story.md` prompt verbatim, parses JSON, runs the faithful-wording validator, retries once on divergence. The existing deterministic stages (render / qa / package) are invoked directly — no duplication, just wiring.

**Decision.** Third option. `pipeline/run.py` orchestrates: ingest → parse → cast (auto-propose + auto-approve rank-1) → render → qa → package. The rest of the pipeline stays untouched — `pipeline/render.py`, `pipeline/cast.py`, `pipeline/package.py`, `pipeline/qa.py`, `pipeline/validate.py`, `pipeline/_memory.py` are reused without changes (except package.py's cover/format additions, which are additive). Auto-approved cast is a simple rank-1 pick from the existing heuristic in `cast.py::_score` — users who want to swap can still do so via the existing CLI. The human is out of the critical path but not out of the kit.

**Consequences.**
- End-to-end run is now one command. Re-runs are cheap thanks to content-hash caching at every stage (parse caches on `source.md` equality; render caches on line hash; package rebuilds are quick).
- Cost: at least one LLM call per new story, which is a real dollar cost. Cached re-renders are free; only the first run pays.
- Auto-approve is coarse: if the heuristic picks wrong, the user has to intervene after the fact (listen to `build/<story>/cast_samples/`, run `pipeline.cast --swap`, re-run). A confidence-threshold follow-up is in BACKLOG — auto-approve only when rank-1 beats rank-2 by a margin; otherwise pause.
- The "Claude Code can orchestrate" affordance is preserved: I (Claude Code) can still call the individual pipeline modules directly when that's ergonomic; the orchestrator is just a nice default for everyone else.

---

## 0022 · 2026-04-16 · `Ingestor` ABC + per-format ingest package

**Context.** Phase 1 accepts raw text, `.md`, `.docx`, `.pdf`, `.epub` inputs. The question was how to structure the format-specific parsing.

**Options considered.**
- **One big `pipeline/ingest.py` with if/elif on file extension.** Simple, but every new format touches the same file; hard to test in isolation.
- **Plugin system with entry points** — overkill for 5 formats.
- **ABC + per-format module** matching the `TTSBackend` pattern we already use in `tts/`.

**Decision.** The ABC + per-format module pattern. `pipeline/ingest/base.py` defines `Ingestor` + `RawStory` / `RawChapter` dataclasses + shared text-normalization helpers; each format gets one file (`text_ingestor.py`, etc.); `pipeline/ingest/__init__.py::get_ingestor(path)` dispatches on extension. Mirrors `tts.get_backend` exactly so the two abstractions feel the same to maintain.

**Consequences.**
- Adding a new format = one file + one line in the factory, same as adding a TTS backend.
- Per-format deps (python-docx, pdfplumber, ebooklib) import lazily inside each ingestor so an install without the `[ingest]` extra still runs `.txt`/`.md`.
- `RawStory.to_source_md()` produces canonical markdown that serves BOTH as the LLM parse input AND as the validator's reference text. Single source of truth for "what the source says" regardless of original format — which means the faithful-wording check works uniformly across formats.
- `.mobi` is deferred: no clean pure-Python option as of April 2026; filed in BACKLOG.

---

## 0023 · 2026-04-16 · `LLMProvider` ABC with Anthropic primary, Gemini optional

**Context.** The orchestrator's parse step needs an LLM. User wants provider choice (primary Anthropic, alternative Gemini) so non-Anthropic users aren't excluded. Phase 2 will add a third provider (MCP sampling) — so the pattern needed to accommodate multiple concrete implementations from day one.

**Options considered.**
- **Hard-code the Anthropic SDK, add Gemini later** — fastest path, accumulates refactor debt.
- **Generic wrapper library (LiteLLM, etc.)** — adds a heavy dependency for a feature we use in one place.
- **Thin ABC modeled on `TTSBackend`** — same pattern, same code shape, swappable in one factory function.

**Decision.** Third option. `llm/base.py::LLMProvider` has one method (`complete(system, user, *, model, max_tokens)`) + `name` / `default_model` class attrs. `llm/anthropic_provider.py`, `llm/gemini_provider.py`, and (Phase 2) `llm/mcp_sampling_provider.py` implement it. `llm/__init__.py::get_provider(name)` dispatches. API keys come from env vars only in Phase 1 (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`); no keys in config, no keys on CLI, no keys on disk.

**Consequences.**
- Swapping providers is a one-line config change (`config.yaml` `llm.provider`) or one CLI flag (`--provider gemini`).
- The two provider modules have nearly identical structure — they differ only in the SDK call. Easy to maintain; easy to add a third (MCP sampling lands in Phase 2).
- Missing SDKs raise `MissingDependency` with the exact `pip install -e '.[llm]'` (or `[llm-gemini]`) command — orchestrator fails fast with an actionable message rather than a bare `ModuleNotFoundError`.

---

## 0024 · 2026-04-16 · Audio-EPUB3 (SMIL Media Overlays) as second output format

**Context.** User wants a second output format alongside `.m4b`. They specifically said "audio-EPUB3" — an EPUB3 package with synchronized text + audio, such that a compatible reader (Apple Books, Thorium, VoiceDream) highlights each paragraph as its audio plays. Not a plain EPUB ebook; not a plain audio file.

**Options considered.**
- **Ship plain EPUB3 (text only) as a secondary export.** Misreads the user ask.
- **Ship audio-EPUB3 via `ebooklib`'s built-in SMIL support.** Ebooklib's SMIL support is thin (documented as experimental); would need a lot of monkey-patching.
- **Write the EPUB by hand with `zipfile` + string templates for OPF / XHTML / SMIL / nav.** EPUB3 structure is small enough to verify against the spec; templates are ~300 lines total; no new dependency.

**Decision.** Third option. `pipeline/epub3.py::build_audio_epub3()` reads `script.json` for chapter/line structure, reads `build/ch<NN>/concat.txt` for per-line WAV durations (already computed during render — no extra synthesis), builds XHTML with `<p id="line_NNNN">` per line, builds SMIL with `<par>` pairs that map each `p` to a `clipBegin`/`clipEnd` in the chapter MP3, assembles OPF manifest + nav + container.xml, and zips via stdlib `zipfile`. Optional cover image goes into the manifest as `properties="cover-image"`.

**Consequences.**
- No new dependency (uses stdlib `zipfile` + `wave` for WAV duration).
- Timing accuracy is perfect: durations come from the actual WAV files the reader will play, not from estimates. First-line-highlighted-when-first-word-plays behavior.
- The chapter MP3 must remain time-aligned with its concat — which it is, since render caches per-line WAVs and stitches deterministically.
- Scene-break lines (`text == "---"`) are rendered as `<hr/>` in XHTML and skipped in SMIL — a break has no spoken content to highlight.
- Users of non-SMIL-aware EPUB readers see a clean text ebook + downloadable audio; users of SMIL-aware readers get the synced experience. Graceful degradation.

---

## 0025 · 2026-04-16 · `MissingDependency` + structured logging as the cross-cutting error UX

**Context.** User flagged mid-build: "If let's say a particular package is not installed, let the interface call it (e.g., it was expecting a whisper thing to take an action but it wasn't available). Also console logging and error logging should be there for error observation and logic fail issues." Two requirements: (1) missing optional deps shouldn't just crash — the system should know which are required vs optional and tell the user what to do; (2) observability for diagnosis after failures.

**Options considered for missing-dep handling.**
- **Bare `RuntimeError` with install instructions in the message.** What we had. Works but callers can't programmatically distinguish "install this" from "other failure" — the Phase 2 UI would have to regex the message.
- **`ImportError` at module load time.** Breaks `pipeline/run.py` imports even when the user's story doesn't need the missing format.
- **Typed `MissingDependency` exception with `required: bool` field.** Callers can catch it specifically; optional missing deps can be skipped with a log line; required ones hard-fail.

**Options considered for logging.**
- **`print` + stderr, like today.** Fine for CLI; nothing structured for the UI to consume.
- **Full structured JSON logging.** Overkill for a local-first tool.
- **Stdlib `logging` with console (INFO, human-friendly) + file (DEBUG, full tracebacks) handlers.** Standard shape; zero new deps; Phase 2 UI can tail the file handler for in-browser status display.

**Decision.** Both: `pipeline/_errors.py::MissingDependency(package, feature, install, required)` + `pipeline/_logging.py::configure_logging(build_dir=...)` emitting to console + `<build_dir>/run.log`. The orchestrator treats required missing deps as fatal (exit 2 with the install command) and optional ones as graceful skips with a WARNING log. Every pipeline stage uses `logging.getLogger(__name__)` — no `print()` inside stage modules.

**Consequences.**
- Whisper QA now skips cleanly when `faster-whisper` isn't installed — the render still ships, the user sees a one-line "whisper skipped — to enable: <cmd>" note in the log.
- Each run leaves a `<build_dir>/run.log` with full tracebacks — when something blows up, the console shows a one-line summary and the file has the stack.
- Phase 2 UI gets a clean contract: catch `MissingDependency`, show an "Install <package>" button that runs `e.install`; for other failures, show the last N lines of `run.log` in a "technical details" disclosure.
- The pattern is load-bearing for the Phase 2 "Use my Claude app" provider option too: if the MCP sampling provider can't reach a connected client, it raises `MissingDependency(required=False)` and the UI falls back to the configured API key.

---

## 0026 · 2026-04-16 · Web UI as plain FastAPI + Jinja2 + SSE, no JS build

**Context.** Phase 2 needed a local web UI. The plan (`.claude/plans/jaunty-popping-kite.md`) called for Apple-HIG design, five-screen flow, voice picker with audio auditions, progress streaming. Options were considered:

**Options considered.**
- **React/Vite/Vue SPA with a JSON API backend.** Richest interactivity ceiling, but pulls in node_modules (40+ MB), a build step, and two-language project. Overkill for a local-first tool that one person uses at a time.
- **HTMX + server-rendered Jinja2 partials.** Server-side truth, small surface, zero JS build. HTMX swaps are fine for form submissions; but voice picker + SSE progress want imperative JS anyway.
- **FastAPI + Jinja2 + vanilla JS (no framework).** Server renders the templates; ~300 lines of vanilla JS handles drag & drop, SSE progress subscriptions, and the voice picker `<dialog>` sheet. No build, no package.json, no node_modules. Works in every modern browser without polyfills.
- **Streamlit / Gradio.** Trivial to stand up but opinionated layout, no way to achieve the Apple-HIG look the user asked for; also heavier dependency footprint.

**Decision.** FastAPI + Jinja2 + vanilla JS. `ui/app.py` holds all routes (pages + API + SSE stream) in one file — a single local-user app doesn't need `routes/` splitting. `ui/templates/` has 8 templates that extend a shared `base.html`. `ui/static/{style.css, app.js}` is the entire front-end. No build step; `python -m pipeline.serve` is everything.

**Consequences.**
- Install footprint adds FastAPI + uvicorn + Jinja2 + python-multipart + mcp (~15 MB). No node_modules.
- Front-end complexity ceiling is low: no state management, no routing, no component tree. For this app's needs (file upload, voice picker modal, SSE progress bar) that ceiling is plenty.
- Accessibility baseline is fine: semantic HTML + `<dialog>` + `prefers-reduced-motion` CSS queries + ≥44pt tap targets. No accessibility debt from React hydration patterns.
- Deploying the UI remotely would be easy (uvicorn + Docker) if that ever becomes a thing, but Phase 2 scope explicitly excludes that.

---

## 0027 · 2026-04-16 · Process-wide backend pool for UI (can't load MLX twice)

**Context.** First end-to-end smoke test of the UI failed with `[Errno 32] Broken pipe` from `mlx-kokoro.synthesize()` whenever the audition endpoint fired after cast proposal completed. Cause: `pipeline/cast.py::propose` called `tts.get_backend("mlx-kokoro")` and held an MLX instance; my new `ui/services/audition.py` called `tts.get_backend("mlx-kokoro")` independently and got a second instance. MLX doesn't tolerate two live pipeline instances in one Python process — the second load corrupts something in the first's state, and the first instance's subsequent synth calls hit a broken internal pipe.

**Options considered.**
- **Serialize all synthesis through one lock** — prevents concurrent calls but still lets two instances exist, and the broken-pipe happens at load time, not during a synth race.
- **Make `tts.get_backend` globally memoizing** — cleanest but changes CLI semantics project-wide (and CLI users intentionally load fresh instances between commands sometimes).
- **Process-wide pool module in the UI layer** — `ui/services/backend_pool.py` holds a dict keyed by backend name, protected by a lock. Cast, audition, and render all call `backend_pool.get_backend()` so the pool has exactly one instance per backend type per UI process. CLI is unaffected.

**Decision.** Process-wide pool in the UI layer. `pipeline/cast.py::propose` gained an optional `backend=` kwarg so the UI can pass its pooled instance; `pipeline/render.py::render_all` gained an optional `backends=` kwarg so the UI can seed render with the same pool. Both kwargs default to None, preserving CLI behavior.

**Consequences.**
- UI process loads each backend exactly once per lifetime. MLX stays happy.
- CLI and `pipeline.run` paths are unchanged — they still load fresh and release at process exit.
- If a user switches backends mid-session via Settings, the previously-loaded backend stays in memory until the server is restarted. Acceptable for a local tool; filed as a low-priority cleanup.
- The synth lock is a coarse mutex — no two synth calls run in parallel within the UI. That matches MLX's actual thread-safety guarantees and keeps the diagnosis simple when something breaks.

---

## 0028 · 2026-04-16 · MCP server as separate invocation, not combined with UI

**Context.** The plan had the web UI and MCP server running in one Python process, so the UI's "Use my Claude app" provider option could use MCP `sampling/createMessage` against a connected Claude client. In implementation, two realities collided:

- Claude Code / Claude Desktop spawn MCP servers via **stdio** — the server's stdin/stdout *is* the protocol. uvicorn also owns stdout for its own logging.
- Sampling requires an active MCP `RequestContext` with a connected client. The web UI has no such context because it's not running as an MCP server.

Combining them in one process means either (a) running the MCP server over an HTTP/SSE transport (Claude Code supports this) and routing sampling through the UI's own server instance, or (b) juggling two event loops with separate stdio handling. Both are real work.

**Options considered.**
- **Ship combined mode now** — significant complexity: HTTP/SSE MCP transport, managing dual lifecycles, registering the HTTP MCP URL in the user's Claude config, handling dropped-client cases during mid-parse.
- **Ship them as separate invocations for Phase 2, defer combined mode** — `python -m pipeline.serve --mode ui` for the browser experience (API-key providers), `python -m pipeline.serve --mode mcp` for Claude Code (stdio, spawn-by-Claude model, tool-based UX). The "Use my Claude app" provider in the UI is present but raises `ConfigurationError` with setup-instructions; it'll light up when combined mode lands.
- **Drop "Use my Claude app" from the UI entirely** — closes the door on sampling support; would require a settings-UI change if it ever comes back.

**Decision.** Second option: ship separate-invocation Phase 2, stub the MCP-sampling provider, document the limitation in the stub's `ConfigurationError.fix` field and in README. Combined mode filed in BACKLOG with the clear requirement: "HTTP/SSE transport for MCP, so the UI process can both host the MCP server AND serve browsers, with sampling routed through a single context."

**Consequences.**
- Phase 2 UI works today for anyone with an Anthropic or Gemini API key. That's the majority of users including the primary one.
- Claude Code users who want tool-based interaction get a cleanly-designed MCP server; they don't touch the web UI at all.
- The one group not yet served is Claude Code users who want the web UI AND want the UI to call Claude for parsing. Their current path is: use the UI with an Anthropic key, OR skip the UI and let Claude Code drive via MCP. Not a hard block.
- The stub provider is useful as a signpost — users who select it in Settings get a clear message pointing at the two working alternatives. Much better than a silent crash.

---

## 0029 · 2026-04-16 · `on_progress` callback on render, threadsafe SSE bridge

**Context.** The UI needed live render progress (line-by-line during the long render stage) without blocking the uvicorn event loop. The render stage synthesizes through MLX / Chatterbox, each call being CPU-bound (~100–500 ms) and unsafe to run on the asyncio loop.

**Options considered.**
- **Subprocess the entire render** — spawn `python -m pipeline.run`, parse stdout lines for progress. Crude, needs log parsing, doesn't share the backend pool (which is exactly the Phase 2 fix for MLX double-load).
- **Refactor render to be async all the way down** — huge change; MLX/Chatterbox aren't async-native and wrapping them wouldn't actually help.
- **Optional `on_progress: Callable[[ProgressEvent], None]` kwarg on `render_chapter` / `render_all` / orchestrator.** Default None = silent. The UI provides a callback that does `loop.call_soon_threadsafe(queue.put_nowait, event)` from the worker thread to a per-job `asyncio.Queue`. The SSE endpoint awaits the queue. Pipeline never imports asyncio.

**Decision.** Third option. `pipeline/_events.py::ProgressEvent` is a pure dataclass with a `to_dict()` for JSON serialization; `emit(cb, event)` is fire-and-forget (callback exceptions swallowed — progress reporting mustn't break a render). `ui/services/progress.py::make_threadsafe_callback` bridges a worker thread to an asyncio.Queue; `stream_events()` converts queue items to SSE frames with 15 s heartbeats and closes on terminal `package:done` / `error:error` events.

**Consequences.**
- Pipeline modules stay synchronous and portable. The web UI is purely additive — it provides a callback, and the existing render loop emits events at chapter start, each line, and chapter end. CLI behavior with no callback is unchanged.
- SSE from the UI is simple: one endpoint (`/events/<job_id>`), one queue per job, heartbeats keep long-lived connections alive. No WebSocket complexity.
- The callback is invoked from the worker thread; callers that do DOM work (the browser) only see JSON events serialized by the SSE handler — there's no thread-safety concern on the browser side.
- Terminal events carry an optional `extra.redirect` URL so the client navigates automatically at stage completion — the UI never polls `/api/job/<id>`.

---

## 0030 · 2026-04-16 · Sniff `.zip` uploads server-side; accept directory-form EPUBs

**Context.** User tried to upload a file they thought was an EPUB. On disk it was actually an **unzipped directory** at `stories/Hyperthief.epub/` with a valid OCF layout (`mimetype` file + `META-INF/` + `OEBPS/`). Browsers transport a dragged directory as a single `.zip` file. The UI rejected the resulting upload with a 400 saying "Unsupported format '.zip'", which the browser then rendered as raw JSON on a blank `/api/upload` page because the form submission was a native POST — no client-side handler to surface the error inline.

Two distinct problems, one user experience:
1. The file content IS a valid EPUB; we were rejecting it because of its extension.
2. Even a legitimate rejection (e.g. a non-EPUB .zip) would land the user on a dead-end JSON page, not a helpful inline message.

**Options considered — accepting the upload.**
- **Trust the browser's MIME type header** (`application/epub+zip`). Unreliable: Chrome and Firefox disagree on what MIME a directory-form upload carries; many tools give `application/zip` or `application/octet-stream`. Can't rely on it.
- **Ask the user to re-export / re-zip manually.** Real option but hostile UX — the user reasonably assumes a folder with `.epub` in its name is an EPUB.
- **Accept `.zip` and sniff after save.** Read the ZIP's `mimetype` entry (EPUB 3.3 OCF requires it). If it says `application/epub+zip`, rename to `.epub` and proceed through the normal extension-based dispatcher. If not, reject with a specific "your .zip doesn't look like an EPUB" error explaining what was expected.

**Options considered — the dead-end JSON page.**
- **Server-side redirect on error** (302 → `/?error=...`). Puts the error in URL state, which the home page would have to read and render. Ugly URLs; browser back-button weirdness.
- **Return a full HTML page with the error** for every 400. Duplicates server-rendering; fights the JSON API pattern the rest of the app uses.
- **Intercept the form submit in JS, render errors inline.** Form now POSTs via `fetch()`; success follows the 303 redirect; failure parses `{detail: "..."}` from JSON and shows it in an `#upload-error` banner. Consistent with how other endpoints already return JSON.

**Decision.** Both fixes, in one commit:
1. `ui/app.py::_save_upload` accepts `.zip` and calls `_looks_like_epub_zip()` (stdlib `zipfile` — no new deps). Valid EPUB zips get renamed to `.epub`; bad ones are unlinked and return a 400 with a specific error message.
2. `pipeline/ingest/epub_ingestor.py` handles directory-form EPUBs by re-zipping to a tempfile (mimetype STORED first, spec-compliant) before handing to `ebooklib`. Same code path works for both UI uploads and CLI `--in` args.
3. `ui/static/app.js::initUpload` intercepts `<input type="file">` change events, submits via fetch, renders inline errors in `#upload-error`.

**Consequences.**
- A user dragging an unzipped-EPUB folder into the browser gets a working upload. So does anyone with a folder-form `.epub` on disk using the CLI.
- A random `.zip` (screenshots, code archive, anything not-EPUB) gets rejected server-side with a message explaining the expected `mimetype` contents.
- Upload errors never again result in a blank page showing raw JSON — they render as a red banner above the drop zone, the file input stays live, the user can immediately retry.
- Client-side extension gate gives instant feedback for obviously-wrong types (`.html`, `.mp3`) without a round-trip.
- Two subtle things: the ZIP sniff is forgiving about mimetype-entry position (EPUB 3.3 says it SHOULD be first STORED, but some tools compress it or reorder). Our `_zip_epub_dir()` on the write-side IS strict — matches the spec for what we produce. And the directory ingestor emits a `warnings.warn()` so the user sees "re-zipped to temp EPUB" in the log, not a silent internal transformation.

**Retrospective lesson.** *When a user calls you wrong, check both bugs at once.* The report was "I uploaded an EPUB and got rejected." The first bug (directory → zip rejection) was real. The second bug (error renders as raw JSON page) is what turned a recoverable 400 into a user-facing failure. Either bug alone is survivable; both together produce a "this product is broken" feeling. The instinct to fix only the reported one would have left the JSON-page-on-error surface waiting to bite on the next legitimate 400.

---

## 0031 · 2026-04-16 · Text-first author extraction for PDF / DOCX; metadata-first for EPUB

**Context.** User asked whether source-file metadata flows through to the generated audiobook. Audit revealed that `RawStory.author` *was* being captured by every ingestor and then silently dropped on the path to `package()` — the output had no `artist` tag at all unless the user passed `--author` on the CLI. While fixing that, a second question surfaced: which source field IS the author?

For EPUB, `<dc:creator>` is a metadata field the publisher authored. It's (usually) right. "Brandon Sanderson," "Jane Austen," etc.

For PDF, the `Author` info dictionary entry is frequently wrong. Authors use a text editor or converter that stamps its own name ("Calibre," "Adobe Acrobat," "Microsoft Office User") into the field, or the field is inherited from a template ("John's Laptop"). For DOCX, same problem: `core_properties.author` is whoever last saved the file on their computer, not the book's author.

**Options considered.**
- **Trust metadata always.** Fast, simple, frequently wrong on PDF/DOCX.
- **Text-only extraction.** Scan the opening page(s) for a byline regex. Reliable when it hits, but EPUB front matter varies wildly and sometimes lacks a byline in the rendered text (cover image carries the author).
- **Text-first with metadata fallback + metadata ban-list.** Try text extraction on the opening page(s). If a confident byline match exists, use it. Otherwise fall back to metadata, but only if the metadata author isn't on a ban-list of known tool names. Per format: PDF and DOCX prefer text; EPUB prefers metadata but cross-checks against text.

**Decision.** Third option. `extract_author_from_text(text)` in `pipeline/ingest/base.py` runs a byline regex (`by X`, `written by X`, `a novel by X`, `author: X`, with optional italic markers) on the first ~800 chars, with guardrails (match must be ≤ 100 chars and not end in a connector word). `clean_metadata_author(name)` ban-lists the known tool names. Per-format policy:
- **PDF / DOCX**: text first, ban-listed metadata as fallback.
- **EPUB**: metadata first (publisher-authored is reliable), but if metadata matches the ban-list, trust text. If metadata and text disagree non-trivially, keep metadata but warn — the user can notice and override.

**Consequences.**
- Hyperthief.epub: metadata gave us `"Sanderson, Brandon"` / `"Patterson, Janci"` (multi-author; we pick the first); text gave us `"Brandon Sanderson"`. Both land at a usable answer.
- PDFs authored in Word-via-Adobe-Acrobat now show the real author instead of "Microsoft Office User." DOCX files saved by someone's laptop show the real author instead of their OS account name.
- The ban-list is an open list — grows as we encounter new tool names in the wild. It's a case-insensitive substring match ("microsoft office user" gets caught by the "microsoft" entry), which is aggressive but safe: real authors rarely have tool names embedded in their names.
- `extract_author_from_text` is deliberately conservative. It requires the byline to be on its own line; it won't match mid-sentence prose like "accompanied by silence." Refuses matches longer than 80 chars. Refuses captures ending in connectors. Better to return None and let metadata take over than produce a garbage author string.

**Retrospective lesson.** *The source's front matter is usually more trustworthy than its metadata, except when the publisher wrote the metadata.* EPUB publishers care about metadata because ereaders display it; PDF producers often don't (the metadata is a side-effect of the editor). When designing an extraction layer, decide per-format which signal is authoritative and encode that as policy, not as a single ranked list.

---

## 0032 · 2026-04-16 · EPUB cover auto-extraction from manifest

**Context.** The user explicitly asked for auto-cover extraction where the source makes it easy. EPUB does: the container declares the cover image via either `properties="cover-image"` (EPUB3) or `<meta name="cover">` (EPUB2). Running tests on Hyperthief.epub exposed two real-world quirks:

1. **ebooklib's `ITEM_IMAGE` type tag is unreliable.** `book.get_items_of_type(ITEM_IMAGE)` returned nothing even when the manifest clearly had image items. Using `media_type.startswith("image/")` as the image check works across versions.
2. **`<meta name="cover" content="Cover.jpg">`** — content pointing at a filename, not an item id. The EPUB 2.0.1 spec says content MUST be an item id. In the wild, Sigil and many other editors write filenames. Handling only ids would miss a large fraction of real-world EPUBs.

**Decision.** `_extract_cover_from_book` with a 3-tier resolution:
1. EPUB3: manifest item with `properties="cover-image"`.
2. EPUB2: `<meta name="cover" content="...">` — try as item id first, fall back to filename match (case-insensitive suffix match, so "Cover.jpg" finds "Images/Cover.jpg").
3. Heuristic: any manifest image whose filename contains "cover".

All image checks use MIME-type prefix (`image/`) rather than `ITEM_IMAGE`, working around the ebooklib type-tag bug.

**Consequences.**
- Hyperthief.epub now yields a 470KB JPEG cover auto-extracted from the manifest (tier 2, filename fallback).
- The extracted bytes get written to `<build_dir>/source_cover.<ext>` during parse. Both the CLI orchestrator and the UI's render path look there when the user didn't explicitly provide `--cover` / upload on the Options screen. User override always wins.
- UI shows a 96×96 preview on the Options screen with "Using the cover from your file — upload a replacement below, or leave blank to keep this one." Visible default, one-click override.

**Retrospective lesson.** *Implementing a spec requires testing against the spec's actual implementations.* The EPUB 2 spec says cover content="" MUST be an item id. Real EPUBs often have a filename there. If you only implement the letter of the spec, you'll silently miss a majority of real-world files. Always ground spec implementations in representative test inputs — on which: the user's Hyperthief.epub found two ebooklib/real-world quirks on first encounter that the spec alone wouldn't have surfaced.
