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
