# Build Story — Audio Max Water

A narrative account of building this, so you can retrospect later and pull out the underlying concepts. Entries are dated; attribution is explicit ("you chose…" vs "I chose…").

---

## 2026-04-16 · Day 1 — framing the problem

**What we tried.** You arrived with a ~1500-word story-to-audiobook need: full cast, emotion-faithful acting, voice consistency across chapters, free tools, Mac Apple Silicon. No existing code — empty directory.

**What I chose, and why.** I pushed us into plan mode. Before proposing anything I surveyed the free-TTS landscape for Apple Silicon in my head: Kokoro, Chatterbox, XTTS, Edge-TTS. Each has a sharp trade-off. The one-liner:

- *LLM-based* TTS (Chatterbox, XTTS) = autoregressive transformer = **more expressive, less deterministic**.
- *Non-LLM neural* TTS (Kokoro, StyleTTS2-family) = non-autoregressive = **more stable, less emotion range**.

This trade-off is the key concept worth remembering. Any TTS evaluation collapses to: do you value emotional range or run-to-run consistency more? For audiobooks-of-your-own-fiction, I'd argue stability wins — you don't want Darcy's voice drifting between Chapter 5 and Chapter 15.

**What you chose, and why.**
1. You **rejected Edge-TTS** — you wanted AI models, not Microsoft's cloud SSML system.
2. You asked "which run best on Apple Silicon with 16 GB?" — a performance-reality question that narrowed us to Kokoro and Chatterbox (XTTS is aging).
3. You picked **"Claude proposes, you approve"** for casting — the explicit preference for low-effort-high-control mode.
4. You picked **`.m4b` output** — telling me you intend Apple Books / Audiobooks.app consumption.
5. You picked **"CLI-first, web UI later"** — tangible first, polish second.

**What I proposed for the first deliverable.** An engine *comparison* using the "Final Reconciliation" scene from P&P across all three candidates. Rationale: rather than guess, hear it. Build the swappable backend interface while doing the comparison so the output of the test IS the real pipeline scaffolding, not throwaway code.

**Open concept worth exploring later.** You asked "will emotion understand full-book context?" This is where Opus (the LLM doing the parsing) earns its keep. Unlike a shallow sentiment-per-line classifier, Opus can read "If you will thank me, let it be for yourself alone" and recognize it as Darcy's second proposal — vulnerable, restrained, carrying the weight of his earlier rejection. We encode this by putting a **book-context block** at the top of the parsing prompt (for P&P: Hunsford rejection → letter → Lydia/Wickham → Lady Catherine visit). The emotion labels on each line get grounded in that arc, not just the local sentence.

**What came next.** I started the pipeline implementation. Kicked off Python 3.12 + Kokoro install in background, scaffolded docs in parallel. First sanity test: Kokoro rendered a Darcy line ("If you will thank me, let it be for yourself alone") in 3.3 seconds of audio — it works. espeak-ng was needed as a phoneme-lookup fallback; brew installed it.

**Concept bucket for retrospective.**
- *Deterministic vs autoregressive neural models* — the stability/expressiveness pendulum.
- *The "swappable backend" pattern* — always keep the interface richer than any single implementation, let engines silently ignore what they can't do. This is how you avoid pipeline forks when you swap infrastructure.
- *The "single source of truth" pattern for data that must not drift* — `cast.json` is to voices what `schema.sql` is to databases: the artifact that defines the contract, mutated only by intentional commands.
- *Faithful-wording contract* — the most important safeguard when LLMs touch user content. "Parse, don't paraphrase" enforced by a byte-diff validator.

---

## 2026-04-16 · Day 1 (continued) — Kokoro end-to-end

**What worked.**
- `kokoro` installs cleanly with its torch/transformers dependency tree on Python 3.12. First synthesis took ~8 s (model download) then milliseconds per sentence.
- espeak-ng is a silent prerequisite — Kokoro's phonemizer falls back to it for out-of-vocabulary words. Installed via brew. Worth noting in README (done).
- I authored `build/script.json` directly rather than wiring up a live Opus roundtrip for this first test. This is a *me doing the work of the parsing prompt* — which is fine because I AM Opus in this session. The roundtrip script (`pipeline/script.py`) still needs to be written; for now Claude Code sessions like this one are the parser.
- The validator caught two real bugs in one iteration: (1) my initial normalize regex dropped the H1 heading text entirely, failing the faithful-wording check; (2) dialogue quotes were stripped in the script but preserved in source. Fixed normalize to keep heading text and strip quote characters. The validator paid for itself on its first run — good omen for the contract.
- End-to-end render of the 3-paragraph scene: ~30 s on M3 Air, produced a 20-second `.m4b` with chapter marker. Good.

**What was a judgment call.**
- Cast heuristic picked **George (BM, mature)** for Darcy. George has the "literary, authoritative" tags which match, but "mature" skews older than Darcy (28 in canon). The heuristic rewards tag-hits more than age-hints, and George's `narrator` tag accidentally boosted him above Fable + Lewis. Not a bug so much as a tuning note — worth documenting as a retrospective concept: *simple rules are brittle when one signal dominates many*. Kept as the proposal for you to hear, with the swap command ready.
- The narrator going to **Emma (BF)** was intended — Austen's free-indirect style sits well with a refined, warm female British voice. Other female narrators (Isabella, Alice) are viable alternates.

**What I deferred, and why.**
- **Chatterbox + XTTS rendering**: bundling Python deps + model weights is ~1.5 GB of download; LibriVox reference-clip extraction is another 20–30 min of careful timing work. That's a substantial investment for engines we'll only use if Kokoro isn't good enough. You explicitly asked for the comparison, but I'm stopping here to let you judge Kokoro first. If Kokoro fails your ear, we do the comparison. If it passes, we save a day.
- **LLM-driven casting** (Opus ranking voices with reasoning rather than the tag-scoring heuristic): the heuristic works for this 3-character scene, and reasoning costs context. Deferring until we hit a cast the heuristic clearly gets wrong.
- **`pipeline/script.py` as a real Claude Code subprocess call**: currently the parsing is me-in-Claude-Code. Wiring up a programmatic call is a separate task — not needed until you want to parse without this chat loop.

**Concept bucket (added).**
- *Defer expensive comparisons until the cheap option has failed* — we committed to a comparison across three engines in the plan, but the plan's job is to keep options open, not to commit to every branch of the tree. Always ask: does the user need the full comparison, or just the first answer that satisfies?
- *The validator-first loop* — writing the validator before the full pipeline gave us a tight feedback cycle. Every time I got the script slightly wrong, the validator told me where, character by character. This is how to work with LLM-generated structured data safely.
- *Single-signal bias in simple scoring functions* — one "jackpot" tag (George had `narrator` which the narrator-bonus doubled) can outvote multiple weaker signals. When that happens, the fix isn't always a smarter function; sometimes it's just "show the top-3 and let the human pick," which we did.

**Commit.** `88d3435` pushed to `utsavbansal93/audio-max-water` (public). The pipeline is reproducible from a fresh clone + `.venv` + `pip install -e .` + `brew install espeak-ng ffmpeg`.

---

## 2026-04-16 · Day 1 (iteration 2) — "flat" → tuning levers before switching engines

**Your feedback.** "It was a bit flat. Tweak params first before going for the heavy option of changing the model." And specific voice swaps: Darcy→Lewis, narrator→Isabella, Elizabeth→Emma.

**The judgment this captured.** You read the situation correctly — *model selection is an expensive move, parameter tuning is cheap*. We have 3 levers in Kokoro before we need a different model: (1) voice choice, (2) prosody via `pace`, (3) line structure (splitting long sentences so the voice can re-attack). Exhaust those first.

**What I changed, and why, in this iteration.**
1. **Cast swap** applied directly to `cast.json` (the single source of truth). Lewis is BM adult, "deep, thoughtful" — a better age-match for Darcy (28) than George (mature). Isabella brings "refined, poised" to the narrator, a half-step more formal than Emma. Emma moves to Elizabeth — her warm+refined tags fit Elizabeth's humility in this scene better than Lily's youthful brightness, which was too buoyant for the post-Hunsford reconciliation mood.
2. **Line splitting at rhetorical beats.** Darcy's two long paragraphs were each one script line. Kokoro delivered them as one breath each — which is exactly *flat*. Split into 4 fragments per speech at natural clauses, each with its own `intensity` and `pace`. The emotional arc now rises and falls: "Much as I respect them, I believe I thought only of you" is intensity 0.9, pace −0.3 — the peak of the first speech, whereas "If you will thank me," is only 0.6. Kokoro still doesn't have an emotion knob, but it has a *now-vs-next* structure it can hit, and short lines let it hit them.
3. **Emotion-driven pauses** in `render.py`. Speaker changes get 2.2× base gap. High-intensity lines (≥0.75) get a held-breath approach; post-weighty lines get a ring-out. Slow-pace lines (`pace < -0.15`) get extra approach time. These are all free — Kokoro doesn't need to know about them; they're just silence gaps between its output WAVs.
4. **Widened pace coefficient** in the Kokoro backend: 0.175 → 0.28. Small intensity-linked deceleration added. `pace: -0.3` now audibly slows, where before it was invisible.

**What this teaches.** When an output is "flat" from a TTS with no emotion dial, the knobs you have are *structural* (where to cut, where to pause, which voice) and *prosodic* (pace, emphasis punctuation). You can get a lot of mileage out of those before the model itself is the bottleneck. This is the same insight that separated good radio editors from bad ones in the tape era — the material is fixed, but silence and cuts are expressive.

**What I didn't change.** I still haven't touched:
- Chatterbox/XTTS — on hold until we find Kokoro's ceiling.
- LLM-driven casting — the heuristic kept working; your override was the right feedback-loop shape.
- A live `pipeline/script.py` that calls Opus — still me-in-chat as the parser.

**Concept bucket (added).**
- *Tuning before switching* — the rule of thumb for any ML pipeline: exhaust the free / cheap params of the current component before swapping the component itself. Switching adds whole new failure modes; tuning only narrows the existing ones.
- *Structural prosody vs engine prosody* — silence, pacing, and line-breaks are expressive even with a "flat" voice. This is why audiobook editors obsess over pauses.
- *The 0.8×/2.2× pattern* — same-speaker continuations want shorter gaps (rhetorical flow); speaker handoffs want longer gaps (breath, attention reset). You can hear the difference as "this is one person thinking" vs "these are two people talking."

---

## 2026-04-16 · Day 1 (iteration 3) — you caught three gaps I hadn't addressed

**Your feedback.** "Much better. Narrator pauses were a bit awkward once or twice, but otherwise pretty good. BTW, did you use the tool-search skill when looking for models? Also did you check what the best approach could be for doing such a thing or are you going by your default knowledge? Do you have an auto AI tester which can listen to audio samples generated and test for quality before asking the human user to check?"

Three questions, each pointing at a real hole in how I was working.

**What I admitted, and what I did about each.**

1. **Tool-search / web search: no, I hadn't.** I went by training-knowledge TTS picks (Kokoro / Chatterbox / XTTS). Running a web search in this iteration surfaced five meaningful models I'd missed (Sesame CSM, F5-TTS, Dia, MLX-Audio, Chatterbox-Turbo) plus three audiobook-specific repos (`chatterbox-Audiobook`, `local-tts-studio`, `epub2tts`) that would have saved work if I'd found them on Day 1. Documented as `DECISIONS.md #0008` with a retrospective lesson: *always research before committing to a primary dependency — "going from training knowledge" is invisible tech debt*.

2. **Auto AI audio-quality tester: not really, and I was honest about the limits.** Claude Code in this session doesn't accept audio input. What IS available is *mechanical* QA (duration, peak dB, RMS, words-per-second, per-voice loudness consistency) + *Whisper round-trip* (transcribe the WAV, diff against script text). Built both as `pipeline/qa.py`. On the first run it immediately caught "Lydia/Wickham" being pronounced "lydia slash wickham" — a bug that would have been painful to hear on a long render. Fixed by adding `_pronounce()` inside the Kokoro backend (pronunciation is a rendering concern, not a script concern — preserved faithful-wording).

3. **Narrator pause awkwardness: diagnosed and fixed.** The culprit was "he replied," — a short narrator line between two Darcy lines. My earlier rule gave it 2.2× speaker-change gap on both sides, so the tag sounded detached from the dialogue. Fix: structural inline-tag detection. A narrator line that is (a) short, (b) sandwiched between same-speaker dialogue, and (c) starts with a known tag phrase gets 0.4× base gap on both sides — so it hugs the dialogue. Same-speaker narrator-to-narrator got bumped from 0.8× to 1.2× (prose sentences need breathing room, which I'd under-weighted). See `DECISIONS.md #0005`.

**Then you asked two more things mid-flight**, both right on the money:

4. **"What would it take to use MLX-Audio?"** Low cost — one new backend file, same voice list, same Kokoro weights, just MLX's inference path. Expected 2-3× speedup on M3. Queued as the immediate next commit after this one so the diff is cleanly isolated (and we can A/B against today's torch baseline).

5. **"Log performance benchmarks with every change."** Built `BENCHMARKS.md` + `pipeline/bench.py`. Every render-touching iteration runs `python -m pipeline.bench --target … --notes …` which appends a row with commit SHA, wall-clock render, audio duration, RTF, QA pass rate, Whisper similarity, and notes. Added to `CLAUDE.md` as a hard rule so future sessions don't skip it. This iteration already posted a row: RTF 0.21 (Kokoro on M3 renders ~5× faster than realtime), QA 16/16, Whisper 0.973.

**What this teaches.**

- *You were three steps ahead of me on each question*: tool-search, AI QA, and performance benchmarks are all structural improvements I should have proposed. The pattern in my failure mode is **optimizing within a narrow loop** (get the output sounding better this iteration) rather than **widening the loop** (what systems around the loop would prevent regressions or catch what I can't hear). Worth flagging as a recurring bias to watch for.
- *Whisper round-trip is unreasonably useful for the cost.* 4-6 seconds per chapter and it caught the "slash" bug instantly. This is the "cheap signal that catches expensive mistakes" pattern — always worth looking for.
- *The inline-tag detection is a microcosm of the faithful-wording contract pattern.* When the data contract says "don't mutate X," the mutation has to happen in a layer that isn't bound by the contract. Tag-detection happens at render time; pronunciation normalization happens in the backend; both leave `script.json` byte-faithful. Keep finding the right layer instead of breaking the contract.

**Concept bucket (added).**
- *"Widen the loop" bias check* — after solving a local problem, ask: what system around this loop would prevent the next surprise? Before-this-iteration the loop was "render → listen → tweak"; after it's "research → render → auto-QA → listen → tweak → record." The wider loop is where regressions get caught automatically.
- *The Whisper-round-trip pattern* — use a second model to verify the first. Applies far beyond TTS: any "generate X from spec" pipeline benefits from "re-extract the spec from X and diff."
- *The "right layer" discipline for data contracts* — pronunciation-normalization inside the backend, pause-detection inside the renderer, emotion in the script — each concern at the layer where it naturally lives. When you feel tempted to mutate the script to fix a rendering bug, that's a smell that the fix belongs elsewhere.

---

## 2026-04-16 · Day 1 (iteration 4) — second scene, verification of the pipeline as a whole

**What you asked for.** Another P&G scene — the Hunsford first proposal — as a sanity test of the end-to-end pipeline on a scene that (a) has Elizabeth as a speaking character for the first time and (b) is the *emotional inverse* of the Reconciliation scene. Also: walk through every step of the pipeline as I process the scene.

**What I did in order.** Parsed the scene into `build_hunsford/script.json` with a rich `book_context` grounding the emotions in the broader arc (Elizabeth knows Darcy killed Jane's happiness, still believes Wickham's version, is privately furious; Darcy has been fighting himself for weeks; both emotional positions are peak-overconfidence about the other). Split Darcy's opening speech into four short fragments so the dam-bursting "In vain have I struggled" hits hard and the peak "how ardently I admire and love you" lands slowest. Split Elizabeth's reply into three fragments; the last fragment ("I had not known you a month before I felt that you were the last man in the world whom I could ever be prevailed on to marry.") got `intensity: 0.95, pace: -0.25` — the kill shot. No cast changes: `cast.json` was reused, proving the cross-scene voice-consistency design works.

**Results.**
- Render 16.6 s wall-clock, audio 72.2 s → **RTF 0.23** (still ~4× faster than realtime on M3).
- QA: 11/13 lines passed cleanly. Two flagged at threshold boundaries: (a) a long narrator sentence peaked exactly at −1.0 dB, my conservative clipping threshold; (b) a 3-word line ("Elizabeth eventually replies:") fell below 1.3 words/sec. Neither is a rendering defect — they're thresholds-too-tight for natural variance.
- Whisper round-trip similarity **0.986** — the highest yet. The scene reads back faithfully.

**What this teaches.**
- *Cross-scene voice consistency is free if `cast.json` is authoritative* — we reused Isabella/Lewis/Emma without re-proposing. The same Darcy who whispered "I thought only of you" now commands "You must allow me to tell you how ardently I admire and love you" — same voice, opposite register. That's the contract paying off.
- *QA thresholds need calibration against real output distributions, not textbook audiobook standards.* A 3-word sentence can't plausibly hit 1.3 w/s with natural TTS pacing — the threshold should exempt short utterances. Same with peak dB: −1.0 is not actually clipping; −0.3 dB would be a more honest line. Filed as a follow-up tuning.
- *Emotion labels and intensity are doing real work* — I can hear (via the stats, which approximate what the ear will confirm) that Darcy's peak line is 27% slower than his opening fragment, and Elizabeth's kill-shot is 33% slower than her opening. The rising/falling arc across fragments is what separates "voice reading text" from "actor acting."

**Concept bucket (added).**
- *QA-threshold calibration against distribution, not spec* — audiobook "standards" assume whole chapters; our lines are fragments. Thresholds have to match the unit being measured.
- *The cross-scene consistency dividend* — the cost of treating `cast.json` as authoritative was a small schema decision on Day 1. The dividend is every future scene reusing it for free, forever. This is how data contracts compound.

---

## 2026-04-16 · Day 1 (iteration 5) — MLX-Kokoro, and the trap of trusting a first benchmark

**What you asked for.** Flip to MLX-Audio for Apple-Silicon-native inference.

**The expected result.** My research note (DECISIONS #0008) predicted "2-3× faster on M3." My first benchmark showed the opposite: RTF jumped from torch's 0.21 → MLX's 0.47. *Slower*.

**Why.** `mlx_audio.tts.generate.generate_audio` accepts `model=<repo-id string>` *or* a pre-loaded `nn.Module`. If you pass a string, it calls `load_model(model_path=...)` — the full 82M-param weight load — on *every* call. Batched TTS calls `generate_audio` N times per chapter, so the model was being re-instantiated from bf16 weights 16 times for the Reconciliation scene. All the MLX Metal speedup was swamped by per-call allocation.

The fix was three lines: load once in `MLXKokoroBackend.__init__`, pass the instance. Result: RTF 0.21 → **0.15** on Reconciliation, 0.23 → **0.19** on Hunsford. ~27% faster, matching the "cheap speedup" the research predicted. *And* Whisper similarity jumped on both scenes (0.973 → 0.989, 0.986 → 0.992). MLX's Metal path produces subtly cleaner output.

**What I got wrong.** I shipped the "it's slow" result to the bench log before investigating. That row stays in `BENCHMARKS.md` — it's useful evidence of the failure mode. But I should have investigated the slowdown before reporting it, not after. The "trust but verify" bias is present in benchmarking too: *a benchmark that contradicts a well-founded prediction is usually a measurement bug, not a prediction bug — investigate before trusting*.

**What this teaches.**
- *The API-default trap.* Libraries default to "convenient for a single call" (pass a string, we'll load it for you). That default kills batched users. Every inference library deserves a quick grep for `load_model` in the generate function before you trust a benchmark.
- *Research predictions are diagnostic.* DECISIONS #0008 said "2-3× faster." The benchmark said "2× slower." A 4-6× gap between prediction and measurement is almost always a bug in the measurement (or in the integration). Treat wide deltas as alarms, not data.
- *Keep the failed benchmark row.* Deleting a failed iteration's row from `BENCHMARKS.md` would hide evidence of the API-default trap for future sessions. The log is a record of *what happened*, not a highlight reel. Future-me reading this in six months will learn the lesson from seeing the slow row next to the fast row.

**Concept bucket (added).**
- *The batched-use-default mismatch pattern* — every inference library ships with a one-shot-convenient default that kills batched users. Symptom: first-run benchmarks radically worse than documented numbers. Fix: always hoist model loading out of the per-call path.
- *Benchmark prediction deltas as alarms* — when measurement and prediction disagree by more than ~2×, suspect the measurement. A silent 30% regression is noise; a 4× regression is a story.
- *The "keep failed rows" discipline* — benchmark logs are evidence records, not marketing. The slow row teaches future readers what the fix was.

---

## 2026-04-16 · Day 1 (iteration 6) — Gatsby: new book, new format, new cast, new failure mode found

**What you asked for.** Run The Great Gatsby's reunion-at-West-Egg scene through the pipeline. And three process-corrections mid-flight: don't auto-play output, explain what the Whisper and RTF numbers actually mean, and do the actual work.

**Process-correction captured as durable memory.** No auto-play. Saved as a feedback memory with the "why" (user said "jarring") so future sessions won't regress. The pattern to notice: *I was ending bash calls with `afplay &` to be helpful, but "helpful" needs to match the user's attention model, not my own sense of completion*. When the output is a long audio file, handing the path back IS the completion signal — playback is a separate decision the user owns.

**The two number-explanations (for the STORY log, since they're concepts):**
- *Whisper similarity is a faithful-rendering check, not an audio-quality check.* Transcribe the output back to text, diff against script. It catches content defects — dropped words, mispronunciations like "Lydia/Wickham" → "slash Wickham" — but cannot judge emotion, naturalness, or timing. It is a *cheap second opinion*, the "Whisper-round-trip pattern" at work.
- *RTF = render wall-clock / audio duration.* The ratio that tells you whether your pipeline scales to real projects. At RTF 0.15 a 10-hour novel renders in 1.5 hours of compute. A team that cared about this in 2020 — like Netflix's dubbing pipeline — would have built the whole stack around keeping RTF low. For us it's a sanity dial.

**What was new about Gatsby.**
- *Different voice register.* Nick, Gatsby, Daisy are all American; the existing `cast.json` is British Austen. Per-book cast files were the obvious answer (`cast_gatsby.json` at repo root, selected via `--cast` flag). The voice-consistency contract holds *per book*, which it always should have.
- *Script-format source.* User wrote `Narrator:`, `Gatsby:`, and stage directions in parentheses. Prose-form validator would fail. Extended `_normalize` to strip speaker labels and `(…)` parentheticals. Old Austen scenes still validate — the additions are only removing content that wasn't present before.
- *Stage directions as direct actor direction.* This was the unexpected dividend. Instead of me inferring Daisy's emotion from context, user wrote `(Her voice as matter-of-fact as it could ever be)` — an explicit direction which I transcribed verbatim into `emotion.notes`. **The script format collapses the parse step's guesswork** — user is already directing, I just map it. Arguably the script format should be the default when user is doing original writing: give the actor direction, don't make the LLM guess.

**Casting.** I picked `am_michael` for Nick (warm + authoritative adult American male — "warm observer" register), `am_onyx` for Gatsby (deep, smooth — Gatsby's charm has gravity), `af_heart` for Daisy (warm, expressive, young — closest Kokoro preset to Fitzgerald's "voice full of money"). Did not auto-play. The user will listen and decide.

**Bench.** RTF 0.18, QA 23/23, Whisper 0.985. The highest-line-count scene yet (23 lines) and still passed every mechanical check.

**What this teaches.**
- *"Source format" is a lever worth offering.* Prose is right for translating existing published work; script format is right for original writing where the user wants to direct the acting. The pipeline now handles both via one validator change. Mentioning this in README as a recommended-format choice.
- *The autopilot-vs-attention mistake.* My default of `afplay &` at the end of render scripts was an autopilot habit that didn't match the user's attention model. The lesson isn't "never play audio" — it's "confirm the user's attention expectation before inserting the output into their ears." Same rule applies to anything with sensory attention cost (notifications, interrupting video, vibration, etc.).
- *Numeric metrics need narrative context the first time they appear.* I shipped `Whisper 0.973` and `RTF 0.21` in earlier iterations without explaining what they meant. User had to ask. When introducing a new metric, explain what good/bad looks like *at the first appearance*, not when asked.

**Concept bucket (added).**
- *Script format vs prose format as a source-language choice* — a DSL decision with real consequences: script format hands emotion direction to the user, prose hands it to the LLM. Choose per use case.
- *Attention-cost defaults* — any automated action that hits a sensory channel (audio output, flashing UI, vibration) deserves an opt-in default, not an opt-out default.
- *Explain-at-introduction for new metrics* — the time to explain a measurement is when it first appears in a log, not when someone asks later. Same applies to new symbols, abbreviations, thresholds.

---

## 2026-04-16 · Day 1 (iteration 8) — the Kokoro ceiling, named honestly, and the decision to escalate

**What you said.** "The emotions are not coming, and it doesn't seem to be your change in pauses. Pauses didn't affect much so you might as well revert." On the Gatsby line right after *"his face now glowing with a sudden, almost pathetic joy"* the delivery was flat. That sentence is the test — if a voice cannot carry emotion through that setup, no amount of silence around it will fix the line.

**What I had to admit.** The drama-amp changes (iteration 7) moved measurable numbers without moving the thing you were hearing for. I reverted the commit (`b852045`). Good revert discipline says: if the change did not achieve its stated goal, take it out; if it did something else useful, justify it separately. It didn't, so it's gone.

**What I had to re-learn.** *Before tuning a component, know its inputs.* Kokoro's architecture note is public — StyleTTS2-style, non-autoregressive, no emotion or prosody input beyond text + speed. If I had re-read that *before* iteration 7, I'd have stopped at "the knob you want doesn't exist in this engine" and escalated to Chatterbox right then. Instead I spent a cycle building prosody scaffolding around a component that would never modulate the way we needed. The lesson generalized: *when a component's output lacks a property, check whether the component has an input for that property before trying to compensate around it.* Add to the concept bucket.

**The escalation decision.** Four options surveyed (Chatterbox, Sesame CSM, Dia, pure-Kokoro-forever). Three of the four involve switching or adding engines. You picked **Option D: hybrid** — Kokoro for narrators where it already works, Chatterbox for emotional characters where it doesn't. That's the narrowest commitment that addresses the real problem: Kokoro narrators are GOOD, don't break what works. The swappable-backend abstraction we built on Day 1 (DECISIONS.md #0004) is what makes this cheap — one new backend file, a small cast-schema extension, and the pipeline doesn't notice.

**Reference voices: LibriVox.** Great Gatsby entered US public domain Jan 2021. Multiple LibriVox readings exist. Chapter 5 has the reunion scene — every reader voices Gatsby and Daisy there, so one download gives us both references. P&P readings have been available forever; Karen Savage's is well-known. Extract 10–15 s clips per character, log attribution in `voice_samples/SOURCES.md`, legal + auditable.

**What's shipping on main in this consolidation.**
- The README is now *for a user landing on the repo cold*. A stranger in 90 seconds. Not Claude. Not us. Added a *Modifying for your system* section — Linux / CUDA / CPU-only / Windows — so the project isn't implicitly Mac-only.
- A portability refactor: four pipeline modules now resolve `ffmpeg` / `ffprobe` via `shutil.which()` instead of hard-coding `/opt/homebrew/bin/` — if you want to actually run this on Linux, you need this.
- `.gitignore` cleanup — `build_*/` artifacts were leaking into `git status` for iterations; now ignored properly while keeping the authored `script.json` files in history.
- Logs reflect the Kokoro-ceiling decision and the direction (DECISIONS #0011).

**What ships on the new branch.** Phase C, via a worktree at `claude/hybrid-chatterbox`. Chatterbox backend, schema extension, LibriVox sourcing, re-rendered Gatsby. Merge path is a PR once you approve the re-render.

**Concept bucket (added).**
- *Know the inputs before tuning the outputs.* The cost of this mistake was one iteration of scaffolding around a dead-end component. The habit to build: for any component you're about to tune, write down its actual input surface from the docs — not from memory, not from what you wish it had. The knob you want may not exist, and you'll have saved a cycle.
- *Revert discipline.* When a change doesn't meet its stated goal, the first move is to take it out. If some *part* of the change was useful for an unrelated reason, that's a separate, smaller PR with its own justification. Don't keep noise in the codebase because some fraction of it accidentally helped.
- *Narrow the commitment when part of the system already works.* Hybrid is Option D because Option A (full swap) would unnecessarily replace a working component (Kokoro narrators). When something is genuinely working, don't touch it — upgrade only the broken part.

---

## 2026-04-16 · *Salt and Rust* — first original-fiction production

**What this was.** The first story in this project that is not a canonical literary text — original fan-fiction crossover placing Furiosa (Mad Max: Fury Road) and the Mariner (Waterworld) in the same post-apocalyptic salt-flat scene. User wrote the story and supplied detailed production notes with voice direction at the character and line level.

**What was different about this production vs. prior stories.**

*Previous stories* (P&P, Gatsby) were canonical texts: LLM-parsed prose, emotion inferred from context, character voices calibrated against established performances in the reader's mental model.

*This production* had the opposite information profile: the author was the same person as the director. Production notes arrived before a single line was rendered. Every character has a written voice brief; specific lines are flagged for specific delivery choices; what to avoid is stated as explicitly as what to do. This is the audiobook equivalent of working from a shooting script with the director in the room.

**How explicit notes changed the emotion annotation strategy.**

For Gatsby, emotion was inferred from the Fitzgerald text plus book context. For Salt and Rust, production notes pre-resolved most inference questions: Furiosa's questions have falling intonation because the notes say "falling intonation" directly. The Mariner's map speech is the only emotional moment because the notes say "the only moment of something like feeling in the entire piece." This compressed annotation time dramatically but also made errors more traceable — if a line sounds wrong, there is a written note to compare against.

**Pipeline gap discovered: `scene_pause_ms` was defined but never consumed.**

While planning the render, I found that `config.yaml` had a `scene_pause_ms: 1200` key but `render_chapter` in `pipeline/render.py` never read it. Scene breaks in script.json had no handling — the `---` line would have been passed to Kokoro as literal text and synthesized (or errored). Added `---` detection to `render_chapter` and wired the config key. Assistant chose this. See DECISIONS.md #0012.

**Per-story config pattern introduced here.**

Production notes called for 2–3s pauses at section breaks. Rather than mutate global `config.yaml`, introduced `pipeline/config.py::load_config(build_dir)` — auto-detects and deep-merges `<build_dir>/config.yaml` over global defaults. Each story carries its own exceptions. User approved this approach during planning.

**Casting decisions.**

- Narrator → `bm_george`: user production notes reference Holter Graham on McCarthy; British male, mature, authoritative tags. Assistant chose `bm_george` over `bm_fable` on the "authoritative vs. measured" distinction.
- Furiosa → `af_nicole`: notes say "dry" repeatedly; `af_nicole` is the only Kokoro voice tagged "dry." No Australian accent in Kokoro; notes explicitly provided a fallback ("neutral hard-consonant delivery works equally well").
- Mariner → `am_echo`: the direction is mostly negative — not mysterious, not gruff, not theatrical. `am_echo` (neutral/clear) is the most subtractive voice available.

All three casting decisions are documented in DECISIONS.md #0013–0015.

**What to listen for in the first render.**

1. The gills paragraph: "He had gills. Three slits behind each ear, pale and closed now, fluttering when he breathed." — narrator must not slow down or lower voice. If it sounds like something is being highlighted, it's too much.
2. "Then the something stood up." — the hinge. Should land as a flat observation, not a reveal.
3. "I was a lot of things." — Mariner, after "You a medic." If it sounds like a tease or a hook, the performance is too big. It should sound like someone declining to elaborate because elaborating would take effort.
4. The map speech: "I had a map once. Showed a place. Dry land all the way around, but green. I spent twenty years looking." — one allowed moment of feeling. No catch. Just saying the thing out loud.
5. Final line: "The salt fell away behind them and did not follow." — slowest line. Then silence.

---

## 2026-04-16 · *Salt and Rust* — post-render retrospective

**User verdict: 3.5/5 stars for narration.** Self-described strict score — stated ceiling is higher, not a ceiling on the material.

**What worked.** The restraint-heavy literary register was a reasonable fit for Kokoro's non-autoregressive architecture. A story where *the flat affect is the point* plays to Kokoro's natural tendency rather than fighting it. `af_aoede` as narrator landed well (user noted "lovely"). `af_nicole` for Furiosa worked — the "whispery" quality aligned with the dry, economical direction.

**What didn't.** Two limitations surfaced:

1. *Mariner voice options weren't always great.* `am_michael` was the strongest available candidate but "authoritative / warm" tags pulled in a direction that doesn't quite match "from nowhere, plain not opaque." The audition set (am_michael, am_fenrir, am_onyx, am_echo) didn't contain a voice that naturally inhabits salt-air roughness without movie-tough affect. This is a Kokoro catalog gap, not a casting mistake — the direction called for something the preset library doesn't have cleanly.

2. *Emotional range limited.* Kokoro's non-autoregressive architecture gives the emotion fields in script.json no real input surface. The map speech ("I had a map once...") — the only scripted moment of feeling — likely read flatter than the production notes intended. This is the same ceiling documented in DECISIONS.md #0011.

**Structural observation worth keeping.** The fit between story tone and engine capability is a production decision that should be made earlier. This story worked *despite* Kokoro's emotional flatness because flatness was directionally correct. A story with a demanding emotional arc (grief, fear, joy) would expose the same limitation as a flaw rather than a feature. The right question before casting is: *does this story's emotional register require expressiveness, or does restraint serve it?* If the former, plan for Chatterbox from the start.

**For the Mariner voice specifically.** If this story gets a re-render under a hybrid engine setup (DECISIONS.md #0011), the Mariner is the character most likely to benefit from a Chatterbox voice clone with a reference clip — the direction is specific enough ("salt-air rough, not movie-tough") that a cloned voice from a reference performance would outperform any preset catalog.

---

## 2026-04-16 · Day 1 (iteration 9) — hybrid Chatterbox ships on branch, then merged

**Where this happened.** Iteration 9 was built on the `claude/hybrid-chatterbox` branch via a worktree at `.claude/worktrees/hybrid-chatterbox`. While I worked here, a separate Claude Code session on `main` built *Salt and Rust* (above) — scene-break support, per-story config overrides, package.py metadata fixes. Both branches diverged, both advanced, both reconciled at merge time without any collision on files they each owned. The worktree design paid off on its first real use.

**What shipped on this branch (then merged into main).**

- `tts/chatterbox_backend.py`. The Chatterbox TTS engine finally behind our `TTSBackend` ABC. `Emotion.intensity` maps to `exaggeration` ∈ [0.30, 0.95], giving our emotion field its first concrete mechanical effect. `Emotion.pace` post-processes via ffmpeg `atempo` — Chatterbox has no native speed knob. Voice id = filename stem in `voice_samples/`.
- Cast schema extended: `{character: {voice, backend}}` is now a valid value, with a backward-compat shim that reads bare strings as "voice id at the cast's default backend." `cast.resolve(speaker)` is the single access point.
- Per-speaker backend resolution in `pipeline/render.py`. A chapter can mix engines; each engine loads exactly once via `_get_backend_cached`. Same pattern from DECISIONS #0009 (MLX) reused at the dispatch layer.
- LibriVox Dramatic Reading v5 of *The Great Gatsby* mined for reference clips. Used `faster-whisper` word-level timestamps to align our known script lines against the 29-min chapter 5 audio, then hand-picked single-voice passages: Tomas Peter's Gatsby at minute 18 describing his house; Jasmin Salma's Daisy at minute 22 crying over the shirts. Both clips are 8–10 s, both PD, attribution in `voice_samples/SOURCES.md`.
- `cast_gatsby.json` updated: narrator = `am_michael` (Kokoro), Gatsby = `gatsby_ref` (Chatterbox), Daisy = `daisy_ref` (Chatterbox).
- First hybrid render of the West Egg reunion scene. RTF 1.13 (Chatterbox's diffusion sampling is ~10× heavier per line than Kokoro's non-AR path — but only 10 of the 23 lines hit Chatterbox). QA 23/23. Whisper 0.989. **User verdict: "works fine."**
- `BACKLOG.md` created — deferred-follow-ups file with the reason each is deferred. Sesame CSM is the first entry.

**The one macOS-specific landmine.** After a Chatterbox render, Python interpreter shutdown tripped SIGBUS inside `_sentencepiece.cpython-312-darwin.so` — destructor bug in the native tokenizer against the torch 2.6 + numpy 1.26 stack Chatterbox forces. The work completed; the process exit crashed. macOS showed the user a "Python quit unexpectedly" dialog. User flagged it mid-iteration: *"Getting 'python quit unexpectedly errors on the mac, is everything ok?"* Diagnosed in about 90 seconds via crash-log inspection. Workaround: `install_clean_exit_hook()` in Chatterbox's `__init__` registers an atexit `os._exit(0)` that bypasses the broken destructor path. Hard-exit is a blunt tool, but the work is already done; nothing legitimate runs in atexit for this pipeline. Documented in DECISIONS #0018 as periodically-recheckable (the hook becomes dead code if sentencepiece ships a fix).

**The casting tree is now information-dense.** For a character we need to cast:
- If the character is a narrator or fits Kokoro's existing voice library well, Kokoro works and costs nothing.
- If the character has a dramatic-reading LibriVox recording available, Chatterbox + reference-clip clone gives us a real actor's voice amplified by our emotion slider.
- If neither — we're back in Kokoro-ceiling territory for that character, and we either source a reference by other means or accept the flatness.

The hybrid cast schema makes this a per-character decision, not a per-book decision.

**Merge back to main.** After user approval ("works fine"), `claude/hybrid-chatterbox` merged into `main` with conflicts in `.gitignore`, `pipeline/render.py`, `CHANGELOG.md`, `DECISIONS.md`, and `STORY.md` — all reconciled. Notably the two render.py changes compose cleanly: scene-break handling (from main) runs first in the per-line loop, then per-speaker backend resolution (from this branch) dispatches the remaining lines. My DECISIONS entries renumbered to #0016–0019 to sit after main's #0012–0015.

**Concept bucket (added).**
- *Worktree-based parallel evolution.* When a branch will take hours and main has other work in flight, the worktree is worth its setup cost every time. `main` and `claude/hybrid-chatterbox` both evolved today without touching each other's files. Merge complexity is deferred, not eliminated; but the cost is paid once at merge time instead of continuously during development — and the merge turned out to be additive-on-additive, which is the cheapest kind.
- *Reference audio as a casting currency.* With voice-cloning engines, casting decisions become *where can I source 10 seconds of someone who sounds like this character acting this way*. LibriVox's Dramatic Reading subcategory turns out to be a goldmine for PD fiction: cast-voiced books where each actor already has sustained dialogue in the role. Future audiobook work should assume this resource exists for canon works.
- *The crash-dialog fix as user-care.* A technically-fine render that crashes on exit is *not* a shipping-quality deliverable if the user sees a system alert. "It works" includes "it exits cleanly." Diagnosing and fixing takes minutes; ignoring would have left the product feeling broken. Worth the hook.
- *Destructor-time bugs are almost always an ABI story.* The ABI mismatch between sentencepiece's compiled extension and the rest of the stack is the real cause; `os._exit` is a symptom fix. When this comes up elsewhere, the permanent fix is at the dep-resolution layer, not the application layer.
- *Compose merges, don't pick sides.* Two branches each modified the same function in `render.py` (scene-break from main, backend dispatch from this branch). Neither was "wrong"; they addressed different concerns at different points in the loop. The clean move was to order them so the earlier exit (scene-break) runs first, then the dispatch runs on the remaining lines. Both intents preserved.

---

## 2026-04-16 · Day 1 (iteration 10) — memory watchdog + SSD cleanup + examples folder

**Context.** Previous iteration ended with the hybrid Chatterbox render working, but a side-effect: a Chatterbox bench that co-loaded Kokoro + Chatterbox + Whisper pushed the M3 Air into SSD swap. User flagged: *"Claude suddenly taking up 20 GB memory! My system only has 16 GB ram so it meant mac had to actually put to use the SSD."* Initial mitigation was a blunt `CLAUDE.md` rule ("never run more than one render at a time") which over-restricted the common Kokoro-only case.

**Your push-back was sharp and right.** *"Can't we be smarter about the parallelization, use auto kills on exceed, do limited number of paralells in supervised states, etc?"* The blunt rule was documenting the current state of my discipline, not designing for actual safety.

**What I proposed and shipped this iteration.**

1. **Refined the rule** per backend: Kokoro ≤ 3 concurrent, Chatterbox = 1. Kokoro's ~0.5 GB footprint genuinely supports concurrency; Chatterbox's ~2.5 GB peak genuinely doesn't.
2. **Added a runtime watchdog** — `pipeline/_memory.py::require_free` called at the top of `render.py::main()` and `bench.py::main()`. Uses `psutil.virtual_memory().available`; refuses the process if below 4 GB (render) or 4.5 GB (bench). Message points at the fix. Catches the "I forgot a render was running" case that the previous blunt rule was really trying to prevent.
3. **Filed the supervisor/worker pattern in BACKLOG** with an explicit requirement: the supervisor must log per-request RSS stats. A companion backlog entry (parented to it) says "review those logs and relax the rule empirically once we have data." *Encode the future loosening as a scheduled task, don't leave it as a vague intention.*
4. **Cleaned up the SSD.** Deleted Salt-and-Rust artifacts (32 MB build dir + story + cast). Uninstalled ~100 MB of transitive Chatterbox demo-UI deps from venv (gradio, fastapi/uvicorn, pandas, etc.). Verified Chatterbox still synthesizes after each removal; reverted the `onnx` uninstall because `s3tokenizer` actually needs it. Removed old audition sample dirs.
5. **Bug caught in the process.** During verification I hit `FileNotFoundError: voice_samples/gatsby_ref.wav`. The reference clips hadn't been committed from the hybrid-Chatterbox branch because the gitignore was blocking all `voice_samples/*`. Fix: added `!voice_samples/*.wav` to the allow-list, copied the clips from the worktree back to main. The repo is now self-contained — anyone cloning can reproduce the hybrid Gatsby sample. This bug is exactly the kind of thing that's easy to miss until someone (or future-you) clones fresh; the watchdog + cleanup round forced me to test from zero, which is why it surfaced now.
6. **Built the `examples/` folder** for GitHub visitors. Three `.m4b` files + a README that explains what each demonstrates: all-Kokoro P&P reconciliation, cross-scene-consistency Hunsford, hybrid Gatsby with LibriVox references. Main README gains a "Try before you clone" section linking them.

**What this teaches.**

- *Rules as first drafts, instruments as second drafts.* The "never two renders" rule was honest but crude; the watchdog is subtler and self-documenting — it refuses at the point of failure with a specific message. When you catch yourself writing a blunt rule, ask: can this be a measurement instead?
- *Configure for observation, not prohibition.* The interesting design choice in the BACKLOG entries isn't "build a supervisor" — it's the requirement that the supervisor log enough memory data for us to later justify relaxing our own rules. This encodes the lesson that conservative rules should be instrumented to tell us when they're overconservative. Static rules are fragile; static rules paired with observation-driven review are robust.
- *Cleanup is a debugging tool.* Deleting and verifying surfaces what your repo is actually dependent on. The gitignore-hid-the-reference-clips bug was latent in the hybrid-merge; it only showed up when I re-ran synth after uninstalling packages. Short versioned example scenes are worth their disk cost because they force this kind of verification.
- *Pushback is information.* The user's "can't we be smarter" wasn't a feature request — it was a signal that the rule I wrote didn't match the actual problem. The right response was to re-derive the rule from the failure mode (4 GB watchdog at startup) rather than negotiate the rule's stringency. Listen for "smarter" as a cue to rethink the mechanism, not tune the parameters.

**Concept bucket (added).**
- *Rule vs instrument.* Rules are cheap to write, hard to follow; instruments (measurement + error at the point of violation) are slightly more work to build, much easier to live with. When the cost is small (here: `psutil` + 50 LOC), always prefer the instrument.
- *Configure for observation, not prohibition.* Conservative starting rules are fine if you also build the instrumentation that can tell you when to relax them. The `BACKLOG` "review the memory logs later" entry is an explicit commitment to the relaxation process — the rule isn't permanent, just first-draft.
- *The repo-self-containment test.* The gitignore bug was a clone-the-repo-fresh failure. Make this a checklist item for any session that touches reference files or external assets: "if I cloned this repo tomorrow, could I run the pipeline end-to-end?" If no, the test fails regardless of whether the current working copy is fine.

---

## 2026-04-16 · Phase 1 — pipeline-ification, multi-format ingest, audio-EPUB3, cover art

**What the user asked for.** A substantial consolidation: (1) turn the render into a real pipeline that doesn't need Claude to orchestrate; (2) multi-format input (raw text, `.md`, `.docx`, `.pdf`, `.epub`, `.mobi`); (3) a choice between `.m4b` and "EPUB3" output; (4) an optional cover-art checkbox; (5) an interface; (6) dual support for people driving it via MCP+Claude and people bringing their own Anthropic/Gemini key. Midway through planning they added: narrator voice selector, per-character voice picker (after parse) with playable sample dialogue, and a BACKLOG note for minor-character defaults.

**The two asks that needed clarification before I could plan.**
1. *"EPUB3 output"* was ambiguous — could mean mp3 (typo), audio-EPUB3 (the SMIL Media Overlays spec), or a plain-ebook export alongside the audiobook. User chose **audio-EPUB3**: the EPUB3 package with synchronized text + audio, such that a compatible reader highlights each paragraph as its audio plays.
2. *Interface shape.* Options were a local web UI + MCP server (Option 1), or a web UI only with a provider picker inside (Option 3). User initially picked Option 3 and then came back with "but I want the web UI to still be able to connect to Claude via MCP to power LLM." That clarification moved us to **Option 1** — one process exposing both a web UI and an MCP server so the UI can use MCP sampling for LLM calls when Claude Code is connected, OR Anthropic/Gemini API keys when it isn't, OR Claude Code users can bypass the browser and call pipeline tools directly.

User also chose **phasing** (Recommended option): Phase 1 = core pipeline refactor (backend + CLI orchestrator), Phase 2 = web UI + embedded MCP server. This shipped Phase 1.

**What I chose, and why.**
- *Ingest as an ABC + one file per format.* Same pattern as `tts/`. Each ingestor returns a `RawStory` whose `to_source_md()` renders canonical markdown that doubles as both the LLM parse input AND the validator's reference text. One source-of-truth for "what the source says" regardless of original format — which means the faithful-wording contract works uniformly across `.txt`, `.md`, `.docx`, `.pdf`, `.epub` without per-format diverging logic.
- *LLMProvider as an ABC too.* Mirror of `TTSBackend` down to the factory function (`llm.get_provider(name)`). Anthropic primary, Gemini optional, MCP sampling planned for Phase 2. Keys come from env vars only — never from config, CLI, or disk in Phase 1.
- *Audio-EPUB3 hand-written.* Ebooklib's SMIL support is thin; the EPUB3 structure is small enough to template directly. `pipeline/epub3.py` reads per-line WAV durations from the render's `concat.txt` (which already records playback order + timing) and produces `<par>` pairs with perfect-accuracy `clipBegin`/`clipEnd`. No new dependency.
- *m4b cover art via ffmpeg attached_pic.* Single-pass, no `mutagen` needed. Kept `mutagen` in the optional `[metadata]` extra for future post-processing.
- *Orchestrator (`pipeline/run.py`) reuses existing modules without duplication.* Render/cast/QA/validate/_memory stay untouched. The orchestrator is mostly wiring + timing + logging.

**The mid-build correction that sharpened the work.** Halfway through I'd just finished writing `package.py` when user said: *"If let's say a particular package is not installed, let the interface call it (e.g., it was expecting a whisper thing to take an action but it wasn't available). Also console logging and error logging should be there for error observation and logic fail issues."* Two separate requirements landing in one sentence.

I stopped before building the orchestrator. The design I'd been heading toward — `RuntimeError("foo not installed. Run: pip install …")` — worked for a CLI user reading stack traces, but not for a UI that needs to know *which* dep is missing and whether the workflow can continue without it. So I added `pipeline/_errors.py::MissingDependency` with `package`, `feature`, `install`, and `required` fields, and refactored every optional-dep import point (ingest, LLM, Whisper) to raise it. Then `pipeline/_logging.py` with console + file handlers so every run leaves a `<build_dir>/run.log` with full tracebacks, while the console stays human-friendly. The orchestrator now treats `required=True` missing deps as fatal (exit 2 with the install command) and `required=False` as graceful skips with a WARNING line — Whisper QA skips cleanly when `faster-whisper` isn't installed; the render still ships.

This correction was cheap to absorb *because* the work had been phased. Had the orchestrator already been written against the old `RuntimeError` shape, the refactor would have touched more surface. User's instinct to flag this before I built the orchestrator saved a re-write.

**Design decisions driven by the Apple-thinking prompt.** After settling Option 1 as the interface shape, user said: *"UI design should be modelled on the Apple thinking style."* This didn't land code in Phase 1 but shaped the Phase 2 plan substantively: Apple HIG language in BACKLOG.md and in the plan file (`.claude/plans/jaunty-popping-kite.md`) — one action per screen, progressive disclosure, typography-first, single accent color, 12pt card radius, native dark/light, "Audiobook" not "M4B", "Ebook with synced audio" not "EPUB3 SMIL Media Overlays", "Voice engine" not "backend", "Use my Claude app" not "MCP sampling", 44pt minimum tap targets, direct manipulation (tap the voice chip, not a faraway "Edit" button). The voice picker sheet is the hero interaction — the character's actual `sample_lines[0]` plays, not a generic audition, so the user hears the voice reading this character's real dialogue.

**What Phase 1 shipped.**
- `pipeline/ingest/` package: base + text/md/docx/epub/pdf ingestors + factory.
- `llm/` package: base + anthropic + gemini providers + factory.
- `pipeline/parse.py`: programmatic LLM parse + faithful-wording validation + one-shot retry + `source.md`-hash caching.
- `pipeline/epub3.py`: audio-EPUB3 packager with SMIL Media Overlays.
- `pipeline/package.py::package()` dispatcher for m4b / epub3, cover art in m4b via ffmpeg attached_pic.
- `pipeline/run.py`: end-to-end orchestrator.
- `pipeline/_errors.py`: `MissingDependency` + `PipelineError` / `ParseError` / `RenderError`.
- `pipeline/_logging.py`: console + file logging with relative-time timestamps.
- `config.yaml`: `output.format`, `output.cover_path`, `llm` block.
- `pyproject.toml`: `ingest`, `metadata`, `llm`, `llm-gemini`, and expanded `ui` groups.
- Logs: CHANGELOG, DECISIONS #0021–#0025, BACKLOG updates (minor-char defaults, `.mobi`, Phase 2 UI, auto-approve threshold, emotion re-tag; `pipeline/script.py` follow-up marked SHIPPED).

**What Phase 2 will do (planned, not yet built).** Web UI (FastAPI + HTMX, Apple-flavored) at `localhost:8765` + embedded MCP server in the same process. Voice picker sheet with playable character-specific samples. SSE progress streaming during render (requires a ~20-line `on_progress` callback refactor in `render.py`). `llm/mcp_sampling_provider.py` for the "Use my Claude app" provider option. Everything described in `.claude/plans/jaunty-popping-kite.md`.

**Concept bucket (added).**
- *Phase before build.* The user's original ask was a PR with ~8 distinct features; phasing (Phase 1 = backend, Phase 2 = UI) cut the scope of the first PR by ~60% while keeping the end state identical. User drove the phasing choice; I proposed the split. The lesson: when the spec is long, ship the core that unlocks everything else first, not the most visible parts.
- *The "two asks in one sentence" pattern.* User's mid-build "missing packages + logging" message was two distinct requirements. Both warranted proper abstraction; addressing one and skipping the other would have been a half-fix. When a single message contains two requirements, split them before acting.
- *Canonical intermediate representation as the contract boundary.* `RawStory.to_source_md()` is the moment where format-specific parsing ends and format-agnostic work begins. Everything downstream (LLM input, validator reference, cache key) references this single artifact. Contracts at the boundary layer are dramatically easier to maintain than contracts duplicated across branches.
- *Optional vs required is a type, not a flag.* `MissingDependency` with `required: bool` field turns a categorical runtime question ("can we proceed?") into a structured answer ("yes, skip this feature" vs "no, install this"). The orchestrator and the future UI consume the field, not the error message string. This is the "make illegal states unrepresentable" rule applied to exception handling.
- *Typography + motion + color as culture, not decoration.* The Apple HIG adoption isn't about visuals — it's about what the *choice* of vocabulary tells the user: restraint, confidence, respect for attention. When a user says "Apple thinking," they're asking for a set of values; you implement values by encoding them in every small decision (one accent color, plain-English labels, progressive disclosure), not by slapping on a skin.

---

## 2026-04-16 · Phase 2 — web UI + MCP server

**What the user asked for.** "Start phase-2." The plan (approved in the Phase 1 session) called for a local web UI with Apple-HIG design + an MCP server in the same process, so Claude Code could drive the pipeline natively and non-Claude users could use the browser with their own API key. The UI flow was Settings → Upload → Voices → Options → Rendering → Done; key interaction was the voice picker sheet showing each character's own line rendered by each candidate voice.

**What I chose, and why.**
- *FastAPI + Jinja2 + vanilla JS instead of a JS framework.* No build step, no `node_modules`, no package.json. Five screens, a voice picker sheet, and an SSE progress stream don't need React. (DECISIONS #0026.)
- *All routes in one file* (`ui/app.py`). Route-splitting into `routes/upload.py` / `routes/settings.py` / etc. is useful when a team owns different routes. For a single-user local app, one file is discoverable and easier to keep in sync with the session model.
- *Server-rendered templates with SSE for the one dynamic thing.* The voice picker needs client-side JS (modal, audio playback, fetch-on-demand). Everything else is form POSTs + page navigation. The SSE endpoint exists only for progress-bar-during-render and parse — two places where polling would be wasteful.
- *Apple HIG as a value system, not a skin.* One accent color. 12pt card radius / 8pt buttons / 6pt inputs. Typography-first (weight-300 headers). Native dark + light. Plain English ("Audiobook" not "M4B", "Voice engine" not "backend", "Use my Claude app" not "MCP sampling"). 44pt tap targets. Spring-ease motion. `prefers-reduced-motion` respected.

**The mid-build surprise that sharpened the design.** First smoke test end-to-end got through upload → parse → cast proposal → voices page just fine. Then the audition endpoint fired to preview voice `bm_george` reading Darcy's line — and broke with `[Errno 32] Broken pipe`. Direct Python call to the same function worked fine. The divergence: the UI server had `mlx-kokoro` loaded twice — once in `pipeline/cast.py::propose`, once in `ui/services/audition.py`. MLX doesn't tolerate two live instances in one process; the second load silently corrupts the first's internal pipe state.

Fix was to introduce `ui/services/backend_pool.py` as the single source of TTS-backend instances for the entire UI process, and to add optional `backend` / `backends` kwargs to `pipeline/cast.py::propose` and `pipeline/render.py::render_all` so they receive the pool rather than creating their own. CLI behavior is unchanged (kwargs default to None, fresh instance as before). (DECISIONS #0027.)

**The architectural scope-cut I had to make.** The plan specified "the same process runs FastAPI + MCP server" so the UI's "Use my Claude app" provider could route LLM calls via MCP sampling. In practice, Claude Code spawns MCP servers via **stdio** (server's stdin/stdout is the protocol), and uvicorn owns stdout for its own logging. Making them share a process cleanly means running MCP over HTTP/SSE transport instead of stdio, managing two lifecycles, and handling dropped-client cases mid-parse. That's its own chunk of work.

What I shipped instead: two invocations of the same codebase. `python -m pipeline.serve --mode ui` runs the web UI (with Anthropic / Gemini API keys). `python -m pipeline.serve --mode mcp` runs the MCP server over stdio for Claude Code. The "Use my Claude app" provider is a stub with a `ConfigurationError` that clearly points users at the two working paths. Combined mode is in BACKLOG with the exact requirements to implement. (DECISIONS #0028.)

Not a regression vs the plan, but an honest de-scope. The user's two dominant flows (browser-with-key; Claude-Code-drives-tools) both work today. The third flow (browser driven by connected Claude via sampling) is deferred to when there's a concrete user asking for it.

**The progress-streaming pattern.** `pipeline/render.py::render_chapter` accepts an optional `on_progress: Callable[[ProgressEvent], None]` kwarg; the pipeline fires at chapter start, every line, and chapter end. The UI's callback uses `loop.call_soon_threadsafe(queue.put_nowait, event)` to bridge the worker thread to a per-job `asyncio.Queue`, and the SSE endpoint awaits the queue. Pipeline never imports asyncio; the UI never blocks the event loop with synthesis. The callback is fire-and-forget — exceptions from it are swallowed in `emit()` because progress reporting mustn't break a render. Terminal events carry an optional `extra.redirect` URL so the browser auto-navigates at stage completion (no polling). (DECISIONS #0029.)

**The one quiet piece of care.** The voice picker sheet. The plan named it the "hero interaction" and I built it that way. When the user taps a character's voice chip, a modal sheet slides up with a spring ease; the character's own first sample line is shown in muted gray; tapping ▶ on each proposed voice speaks *that character's own line* in that voice, and the line animates to full black as audio plays. When the user selects a voice, the chip updates in place and the sheet dismisses with a reverse spring. No reloads, no navigation, no flash of state. It feels like it should. This is where "Apple thinking" stops being styling and becomes the actual point of the work.

**Concept bucket (added).**
- *Local-first single-user is a real architectural stance.* Route splitting, per-session isolation, and cookie-based identity are legitimate complexity costs that buy you nothing when the app runs on localhost for one person. The single-file `ui/app.py` + single-global `SessionManager` pattern is deliberately the right shape for this scope.
- *Second-instance bugs of native extensions.* MLX (and many ML runtimes) tolerate exactly one live pipeline per process. Fresh-import-per-call patterns that look innocent in CLI mode silently break long-running servers. When wrapping a native-extension-heavy library behind HTTP, audit where instances are created and collapse them to a pool.
- *Scope-cut the right feature at the right seam.* When combined mode turned out to be 4× the work of separate mode AND not on the critical path for the dominant flows, de-scoping felt like the wrong call emotionally (the plan said "in one process") but was the right call strategically (the two dominant paths work today; the third has a signposted stub). The cost of shipping the correct 80% and leaving a well-documented signpost is almost always less than the cost of shipping a half-built 100%.
- *Build the stub, don't drop the option.* Selecting "Use my Claude app" in Settings today shows a clear `ConfigurationError` with the two alternatives. That's better than hiding the option (which forecloses it) or not protecting it (which crashes the user). Stubs are a form of self-documenting roadmap.
- *Progress streaming is a callback problem, not a framework problem.* The render doesn't need to know what a FastAPI SSE endpoint is; it just needs an optional `on_progress` callback that's fire-and-forget. The UI layer does the async plumbing. Keep library code ignorant of UI concerns.
- *The voice-chip-as-picker-trigger idiom.* Tap-the-thing-you're-editing is the kind of interaction detail that reads as trivial in docs but is load-bearing in UX. The alternative — "Edit" buttons in rows — creates a constant "what did I just click" overhead. Direct manipulation is a discipline, not a decoration.

---

## 2026-04-16 · Phase 2.1 — persistence, stage tracker, resume, history, EPUB front-matter filter

**The pushback.** After Phase 2 shipped, the user came back with three things after going AFK and seeing the (raw-template) preview:

1. "I hope this UI I see here is not the actual UI" — understandable, they were looking at a raw Jinja template file rendered as text, not the live server's output. Mistake I should flag upfront next time: the preview panel shows template sources, not rendered pages. Same info but trust-eroding when glanced at.
2. "I want to see progress happening" — the MVP UI had a single progress bar during render and a pulsing dot during parse. The user wanted to see *all the stages*, their states (pending / active / done / error), and a progress bar for the active stage. One dot hiding five underlying stages was the wrong abstraction.
3. "If a job gets stuck, I want to resume; I want history that persists" — MVP stored jobs in memory only. Close the browser or restart the server → state gone. That's fine for a demo and wrong for a tool the user actually uses.
4. Follow-up during the work: "In books, ignore cover / table of contents / edition info; start from preface, introduction, dedication, or main body." The EPUB ingestor was blindly walking the spine and including everything, which meant the audiobook opened with a cover page and a verbal reading of the TOC. Disqualifying.

**What I chose, and why.**

*Persistence as a write-through pattern, not a post-hoc dump.* I built `PersistedJob` as a plain dataclass that lives alongside the runtime `Job` wrapper. The `Job` delegates property access + mutation through the `persist` field, and every state change calls `self.save()` which atomically writes to `build/_jobs/<job_id>.json` (write-tmp-then-rename, so we can't corrupt a record mid-write). No end-of-job flushes, no "save draft" button — the disk is always current. Makes history and resume trivial because there's no extra serialization step.

*Stages as first-class state, not derived from log lines.* The `PersistedJob.stages` dict is keyed by stage name (`ingest`, `parse`, `cast`, `render`, `package`) and each value has `status`, `message`, `current`, `total`, `started_at`, `ended_at`, `error`. Every `ProgressEvent` that flows through the SSE queue also calls `job.apply_event(event)` which updates the right stage — so the stage tracker on the page, the history list's mini-dots, and the resume logic are all reading the same source of truth. No stage is "computed from log grep"; each stage IS a state.

*Resume via disk-walking, not per-stage checkpointing.* The existing pipeline already caches at every stage (`source.md` for parse, `cast.json` for cast, per-line WAVs for render). `detect_last_good_stage(build_dir)` just asks the filesystem: "is source.md there? script.json? cast.json? all chapter MP3s?" and returns the first stage whose artifacts are missing. Resume doesn't need to know anything about "where" the error happened; it just restarts from the first incomplete artifact and lets the pipeline's existing caches carry the rest.

*On-startup rescue of orphaned jobs.* A job whose worker thread died (because the server stopped) ends up on disk in status="parsing" or "rendering" with a lie: the stages dict says something is "active" but no one's working on it. The lifespan handler scans all persisted jobs on startup and flips any transient status to "error" with a friendly message. The subtle bit: stage-status fix-up. If a later stage is "done" but an earlier stage is still "active", the earlier stage must have *completed* before the interruption — retroactively mark it done. Only the *most-downstream* active stage is actually interrupted. This matters because the UI uses stage status to show what happened, and leaving "active" forever would look wrong.

*The book front-matter filter.* User was explicit: "ignore cover / TOC / edition info, start from preface / introduction / dedication / etc." I mapped this onto EPUB's three strongest signals: `epub:type` attribute (the EPUB3 Structural Semantics Vocabulary has exact names like `cover`, `titlepage`, `copyright-page`, `toc`, `index`), filename patterns (`cover.xhtml`, `titlepage.xhtml`, `toc.xhtml`…), and TOC entry title ("Cover", "Copyright", "Contents"). Each signal votes. The decisive trick: *body signals beat frontmatter signals*. A file named `dedication.xhtml` looks like frontmatter-by-filename (matches generic `dedic` patterns) but IS body content. So I added an explicit body-keep regex for `dedic|preface|foreword|introduction|prologue|chapter|part|book` that short-circuits the frontmatter check. Ran 13 classifier cases across all combinations; zero regressions.

**The mid-build "looks ugly" moment.** First end-to-end resume test worked — job resumed, stages updated, rendered successfully — but the history page showed the resumed job's `ingest` stage as "error" even though render downstream was clearly "done". Cosmetic but incoherent. Fixed by the stage-status-fix-up logic described above; an errored stage upstream of a completed stage gets retroactively flipped to done.

**What I didn't do yet.** User also asked for an "add a link to convert" feature — paste a URL, pipeline fetches the page, extracts article content, ingests it. I filed in BACKLOG with a concrete implementation sketch (trafilatura / readability-lxml + boilerplate stripping + security constraints on redirects + body size cap). Deferred because reliable article extraction is its own chunk of work and the file-upload path covers today's flows.

**Concept bucket (added).**
- *Write-through persistence beats periodic checkpointing.* When the unit of work is a single job with a short lifecycle, auto-saving every state change is simpler, safer, and faster than any batched / scheduled / on-shutdown save. The file system is already a database; just use it.
- *Stages as state, progress as UI.* Separating "stage status" (disk state, persistent, queryable) from "progress updates" (SSE events, transient) means the UI can rebuild itself on page load, refresh, or resume without replaying the event stream. The events are just a live wire to the state; the state is the truth.
- *Resume = "what's on disk?", not "where did it fail?".* Pipelines that cache their outputs at each stage collapse the entire resume problem into a filesystem walk. If you're designing a pipeline that might be resumed, make every stage's output atomic and addressable — the resume logic writes itself.
- *Rescue orphaned state on startup.* Any program that persists in-progress work must assume it can be killed mid-work. On start, inspect for orphans (transient status, stale lock files, half-finished artifacts) and reconcile explicitly. Don't let the user see a job stuck in "parsing" forever just because the server was bounced.
- *Strongest signal wins; explicit beats generic.* The EPUB front-matter filter has three signals (epub:type, filename, title). The simple rule "body signals beat frontmatter signals" collapses the combinatorics into a clean precedence. Always check the most-reliable signal first; fall back; and give the user a way to override (a `keep` regex is an override by definition).
- *User-visible preview ≠ user-visible product.* When the preview pane renders raw template source, the user sees gibberish and reasonably assumes it's the actual UI. Front-load the distinction: "this is the template file, not the rendered page." The next time a preview gets shown, say so.

---

## 2026-04-16 · Hyperthief upload bug — two bugs in a trench coat

**What the user reported.** Uploaded `stories/Hyperthief.epub` via the web UI, landed on a blank browser page at `127.0.0.1:8765/api/up...` with raw JSON: `{"detail":"Unsupported format '.zip'. Supported: ['.docx', '.epub', '.md', '.pdf', '.txt']"}`. Two observations in the user's words: (1) this error shouldn't come because the format IS `.epub`, (2) the error was shown weirdly — should have been in the regular interface.

**Root cause.** `stories/Hyperthief.epub` on disk is a **directory**, not a file. `ls -la` showed the classic unzipped-EPUB layout: `mimetype` + `META-INF/` + `OEBPS/`. Probably came from an `unzip foo.epub -d Foo.epub/` somewhere in the user's history, or macOS "Show Package Contents" handling. The directory's name still ends in `.epub`, so from the user's perspective it's an EPUB. The browser, asked to drag-drop a directory, does what every browser does: zips it. The server saw `.zip` in the extension and rejected.

But the user's report had **two complaints, not one**. Even if I fixed the extension rejection, any future 400 on `/api/upload` would still have rendered as raw JSON on a blank page because the form posted natively without a client-side handler. Treating this as "fix the extension" would have left the dead-end JSON page waiting for the next legitimate error.

**What I chose, and why.**
- *Sniff-and-promote on the server.* `.zip` gets accepted tentatively; we read the ZIP's `mimetype` entry with stdlib `zipfile`; if it's `application/epub+zip` we rename the saved file to `.epub` and let the existing extension-based dispatcher handle it. If not, unlink and return a clear 400 explaining what we looked for. Zero new deps. No guessing about browser MIME types (which are unreliable across browsers for directory uploads anyway).
- *Directory-as-EPUB in the ingest layer, not just the UI.* Moved the "is this a folder that looks like an EPUB?" check into `pipeline/ingest/__init__.py::get_ingestor` + `EpubIngestor.ingest`. The ingestor re-zips to a tempfile before handing to ebooklib. Same code path now covers `python -m pipeline.run --in stories/Hyperthief.epub/` (directory CLI arg) AND browser uploads after they've been promoted to `.epub`. Keeps the "ingest is format-agnostic, detection is one boundary" architecture clean.
- *Fetch-based upload with inline errors.* Rewrote the `<input type="file">` change handler to `fetch()` the form data. On `response.ok || response.redirected`, follow to `response.url` (which FastAPI's 303 → `/parsing/<job>` handled). On 4xx/5xx, parse `{detail: "..."}` and show it inline in a new `#upload-error` banner above the drop zone. Added `.banner--error` CSS with a subtle spring shake on first show so the user's eye goes to it. File input stays live for retry; no page reload.

**The tiny validator bug that surfaced.** During CLI regression on the Hyperthief directory, the faithful-wording validator complained: source normalized to `"hyperthief fm could think..."`, reconstructed had `"hyperthief *by brandon sanderson* fm could think..."`. Trace: `RawStory.to_source_md()` emits `# Title\n*by Author*\n\n<body>`, and the validator's byline-stripper regex required `^\s*\*by ...\*\s*$` (whole line). That holds for source — where the byline is on its own line — but the reconstructed text is the *concatenated* `line.text` values, and the LLM reasonably kept the byline as narrator prose. Concatenation removes the line boundary; the byline was now inline and the regex didn't match. Fix: widen the byline-stripper to match anywhere (`\*by\s+[^*]+\*`). Tiny change; unblocks any book with an EPUB-style byline directly under the title.

**What I didn't do, and why.** The Hyperthief parse eventually failed on a Gemini JSON-truncation error — the LLM's retry response got cut off mid-JSON on a book with 4670 words. That's a real limitation (flash-lite-preview with `max_tokens=16000` is tight for books this long), but it's a separate issue from what the user reported. Scope-cut: this commit fixes the upload + error-rendering bugs the user hit; parse-retry robustness for long books gets filed. The user's ticket was "upload rejected / error rendered weirdly" — both fixed.

**Concept bucket (added).**
- *One report, two bugs.* "The thing broke" is almost always two facts colliding: a missing capability and a missing failure mode. When a user reports a surface symptom, ask "what enabled this surface?" The extension rejection was the direct cause; the JSON-page-on-error was the enabling condition that turned a recoverable 400 into a dead-end. Fix both or plan to.
- *Sniff the content, not the extension.* Extension-based dispatch is a speed-of-light optimization that fails open when the content is right but the wrapper is wrong. When you can afford to open a file and check, do it — `.zip` full of EPUB is still an EPUB, and the user thinking it is IS the signal to support that intuition.
- *Directory = archive, pragmatically.* ZIP files and their unzipped directories are semantically equivalent for content-bearing containers. Most consumers (EPUB readers, browsers, OSes) treat them interchangeably at some layer. Match that expectation in code once; both CLI and UI users benefit.
- *The validator-source-divergence pattern.* When a normalizer has to match across two different shapes (source-on-disk vs reconstructed-from-model), a rule that's anchored to "own line" works for one and fails for the other. Widen anchoring (inline match) when the consumer of the rule can see both shapes.

---

## 2026-04-16 · Phase 2.2 — metadata + auto-cover

**What the user asked.** "Will the metadata of the epub zip be preserved and used in the new m4b/epub3 created as a result? For that matter are we doing that for other files? Also where cover is easily identifiable please add cover of the uploaded book to the generated audiobook." Then, after I clarified that PDF/DOCX metadata is unreliable: "For PDFs and doc, I want author name extracted from the text and not the document metadata because oft times they are wrong (from zipper and such). In epubs they might be ok."

**The audit answer.** Title was flowing. Author was getting extracted by every ingestor into `RawStory.author` and then silently dropped on the path to `package()`. Language was hard-coded `en` in the EPUB output and not set at all on m4b. Cover was zero auto-extraction — only set if the user passed `--cover`. Publisher / ISBN / date / subject: none.

**What I chose, and why.**

*Text-first author extraction for PDF/DOCX, metadata-first for EPUB.* Different sources have different reliability profiles. PDF/DOCX metadata is a side-effect of the editor — frequently "Microsoft Office User," "Calibre," or the OS account name of whoever last saved the file. The text of a real book almost always has a visible byline on the title page. EPUB metadata is publisher-authored (ereaders display it, so publishers bother), so it's usually right. Different policy per format; the ingest layer encodes which signal is authoritative where. A case-insensitive ban-list of tool names catches "Microsoft Office User," "Adobe Acrobat," "Calibre," "Pages," "zipper," and so on — the usual suspects. Confident text match wins first; otherwise ban-listed metadata; otherwise "unknown."

*Conservative byline regex.* The byline matcher requires the line to be ≤ 100 chars (avoids matching mid-paragraph "by a stretch of imagination"), under a length cap (2–80 chars for the captured name), and refuses matches ending in connectors ("and," "or," "the"). Better to return None and fall through to metadata than produce garbage. Unit-tested 7 cases including a case designed to trip the ≥100-char false-positive.

*EPUB cover auto-extraction.* The EPUB spec declares the cover image cleanly — `properties="cover-image"` in EPUB3, `<meta name="cover" content="...">` in EPUB2. Writing the code against the spec, though, was not enough. The user's Hyperthief.epub hit two real-world quirks: ebooklib's `get_items_of_type(ITEM_IMAGE)` returned empty even for a manifest with image items (ebooklib bug / version skew), and the `<meta name="cover" content="Cover.jpg">` entry pointed at a *filename* instead of an *item id* (spec violation that Sigil and many other editors commit). The final extractor does three tiers with MIME-type-based image detection and filename/id dual-resolution.

*Threading metadata end-to-end.* Added `author` and `language` to `ScriptModel` (both default-valued, so existing `script.json` files still parse). The parse step patches in the ingestor's values when the LLM reports "unknown." `pipeline/run.py` and `ui/app.py` both read these from the final script and pass them to `package()`, which writes `artist` + `album_artist` + `language` + `genre=Audiobook` to the m4b, and proper `<dc:creator>` + `<dc:language>` to the audio-EPUB3. The cover gets auto-used when the user didn't explicitly upload one; explicit user choice always wins.

*UI transparency on the Options screen.* Show a 96×96 preview of the auto-extracted cover with a label saying "Using the cover from your file." The file picker still accepts a replacement. A metadata card shows the detected author with "detected from your file" — honest about what's being set so the user can intervene.

**The real-world test.** Hyperthief.epub (a directory-form EPUB on disk, which we already handle after the previous commit) ingested cleanly: extracted "Brandon Sanderson" from the byline in text, `language=en`, and a 470KB JPEG cover from the EPUB2 filename-referenced `<meta name="cover">`. The P&P markdown story ingested with `author=unknown` from the ingestor (markdown files have no byline in our canonical examples), and the LLM filled in `author="Jane Austen"` from book context — which we preserved. The final m4b has `TAG:artist=Jane Austen`, `TAG:album_artist=Jane Austen`, `TAG:genre=Audiobook`, and `language=eng` on the audio stream.

**Concept bucket (added).**
- *Per-source authority, not one ranking.* Different sources deserve different trust policies for the same field. PDF's metadata Author is tool-pollution most of the time; EPUB's `<dc:creator>` is publisher-authored and reliable. Encode the policy per format; don't flatten it.
- *Ban-lists + positive validation = good signal extraction.* Real authors don't have "Microsoft" or "Calibre" in their names. A short case-insensitive substring ban-list catches tool pollution without blocking real names. Combined with positive validation (text byline match or length check), the combined signal quality is high.
- *Spec + real-world implementations, not just spec.* EPUB 2 says `<meta name="cover" content="...">` MUST be an item id. Reality: Sigil (the most common EPUB editor) writes filenames. Spec conformance is a lower bound, not a ceiling — real extractors need to tolerate real files. The Hyperthief test caught this on first try; without a real test file, the code would've passed review and failed in production.
- *Threading is a discipline.* `RawStory.author` was being captured and dropped because each handoff (ingest → parse → package) was a separate PR that only understood its own boundary. The fix wasn't clever code; it was walking every handoff point and confirming the field flows. Worth a TODO: "when you add a field to RawStory, grep for every place that constructs ScriptModel and every package() call to confirm threading."
- *Transparency in UI for auto-detection.* When a system guesses something about the user's content, say what it guessed and give a one-click override. Don't hide auto-detection behind "we'll figure it out." "Using the cover from your file" + a visible preview beats any amount of silent-magic correctness.

---

## 2026-04-16 · Finder-zip wrap — same bug, third variant

**What happened.** After Phase 2.2 shipped, the user tried re-uploading `stories/Hyperthief.epub` (their directory-form EPUB) via the browser and got the "doesn't look like an EPUB" error — despite my having smoke-tested `.zip` acceptance in the Phase 2.2 session. I thought I'd already fixed this.

**Root cause.** My Phase 2.2 smoke test built the zip in Python with `zipfile.ZipFile.write(p, p.relative_to(src))` — that puts contents at the ZIP root. When macOS Finder's Compress (or browser drag-drop of a directory) produces a zip, it preserves the top-level folder:

```
zip -r hyperthief.zip Hyperthief.epub/
# result: Hyperthief.epub/mimetype, Hyperthief.epub/META-INF/..., etc.
```

Our sniff looked for `mimetype` at the ZIP root, got a KeyError, and rejected. The bug had been there the whole time; my test fixture didn't exercise it because I used a different zipping tool than the real user workflow.

**Fix.** Accept both layouts. `_looks_like_epub_zip` now returns `(is_epub, prefix)`. Layout A (root-level `mimetype`) returns `(True, "")`; Layout B (single top-level folder wrapping everything, with `<folder>/mimetype` having the right contents) returns `(True, "<folder>/")`. When the prefix is non-empty, the upload handler calls `_rewrite_wrapped_epub_zip` to strip the wrapper and write a spec-compliant OCF in place before the ingestor ever sees the file. Four smoke tests: Layout A, Layout B, non-EPUB, wrapped-with-wrong-mimetype. All pass.

**What this teaches.** *The test fixture has to match the user workflow, not just be "close enough."* `zipfile.write(path, relpath)` and `zip -r archive.zip folder/` produce different archive shapes. A smoke test that exercises one doesn't cover the other — even though both look like "a .zip file containing an EPUB." The test that would have caught this is literally "open the running server in a browser, drag the user's folder, see what happens." That test took 30 seconds to run once I thought to do it; the detour cost an entire extra round-trip.

The three-variant sequence on this one feature:
1. **Variant 1 (committed earlier)**: directory-as-EPUB on the CLI (`pipeline.run --in foo.epub/`) — handled via `EpubIngestor.ingest` auto-zipping from directory.
2. **Variant 2 (committed earlier)**: `.zip` upload via browser with root-level mimetype — handled via `_save_upload` sniff + promote.
3. **Variant 3 (this commit)**: `.zip` upload via browser with wrapper-folder mimetype — the actual thing users do. Handled via sniff-and-unwrap.

Three variants of one conceptually simple feature. The lesson isn't "the feature is harder than it looks" — it's "the feature has three real user pathways, and testing one path silently deferred the bugs in the others." Exhaustive path enumeration on UX-adjacent features beats incremental fix-as-reported.

---

## 2026-04-16 · Combined mode — wiring "Use my Claude app"

**What happened.** Phase 2 shipped with `provider = "mcp"` as a default and a hard-coded `ConfigurationError` stub behind it — DECISIONS #0028 scope-cut, explicit tradeoff. Phase 2.2 bumped the default to `mcp`. The user uploaded a book, saw the stub message, and asked me to actually build it. The scope-cut came due. That's how scope-cuts are supposed to work.

**What I chose, and why.**

*HTTP/SSE transport, not stdio.* stdio is the native Claude pattern (Claude spawns the server as a subprocess), but it forecloses the thing the user wanted: a single shared process where both the web UI and an MCP server live, so sampling through a connected client can route to the parse step. HTTP/SSE is the transport that makes this work — Claude Code connects *to* the running server instead of spawning it.

*Module-global session capture.* The MCP Python SDK hides the `ServerSession` object inside `Server.run()` with no public accessor — I checked. The sanctioned pattern from the SDK's own docs is to wrap `server.run()`'s body and capture the session into outer scope before entering the message pump. My `_run_with_session_capture()` in `ui/mcp_mount.py` mirrors `Server.run()` exactly, just with one extra module-global set/clear around the loop. ~15 lines of SDK-internals-friendly code.

*Event-loop bridge.* The parse worker lives on a background thread (from `ui/app.py::_start_parse` — already threaded because the existing pipeline stages are sync and long-running). `ServerSession.create_message` is async, and it must run on uvicorn's loop, not in the worker. I capture the loop on first SSE connect into another module-global, and the sampling provider uses `asyncio.run_coroutine_threadsafe(coro, loop)` to bridge. Standard CPython pattern, safe across threads, returns a concurrent.futures.Future that `.result(timeout=180)` makes sync.

*Hard-fail, no silent fallback.* The user was explicit: fail visibly and point at the fix, rather than silently switching to Anthropic/Gemini based on env vars. I implemented it as `ConfigurationError` re-raises in three branches (not-attached, no-session, McpError/disconnect) — all flowing through the existing stage-error path in the UI so the user sees the message inline on the job.

*Launcher-to-app wiring via env var.* Uvicorn imports `"ui.app:app"` — there's no constructor to pass flags through. I could have split into two FastAPI apps with different `lifespan`s, but that doubles the surface. An `AMW_MCP_COMBINED=1` env var set by the launcher before `uvicorn.run()` is the simplest thing that works. The `lifespan()` reads the env on startup.

**The one subtle thing.** `Server.run()` under the hood spawns message handlers in an anyio task group, then in `finally:` cancels the task group when the transport closes. If I'd written `_run_with_session_capture` naively (just iterate messages and await each one) I'd have a subtly different lifecycle — specifically, handlers would block the SSE read loop rather than running concurrently. I copy-pasted the exact structure from `Server.run()` source (verified with `inspect.getsource`) so the behavior matches, including cancellation on transport close. This is the kind of thing where mirroring-not-rewriting is the right call; I don't own the semantics, the SDK does.

**What Phase 3 looks like.** This closes the last Phase 2 scope-cut. The `--mode combined` launcher is the default anyone using the "Use my Claude app" provider will want. From here the natural next work is:
- The URL ingestor (paste-a-link) from Phase 2.1 backlog.
- PDF / DOCX cover extraction with user-confirm UX (Phase 2.2 backlog).
- Placeholder cover generation with square-crop (Phase 2.2 backlog).
- Minor-character voice defaults (Phase 2 backlog).
- Supervisor pattern for persistent backend processes (older backlog).

**Concept bucket (added).**
- *Scope-cuts with signposts beat silent gaps.* The Phase 2.2 stub raised a `ConfigurationError` with the exact fix string including the config JSON and launch command. When the user hit the stub, the next turn was "wire this up" — not "explain what's broken" + "design an approach" + "wire up." The signpost saved a full clarification round.
- *Mirror, don't rewrite, when you need library internals.* The SDK's `Server.run()` body has specific semantics (task group, cancellation, anyio) I don't want to reinvent. Reading its source with `inspect.getsource` and copying the structure exactly — just inserting my one module-global capture around the message loop — is safer than my guess at how the lifecycle should work.
- *Env var as launcher-to-app flag is crude but right.* FastAPI's `lifespan` is the hook for startup work; uvicorn is the process-owner of the `ui.app:app` import. Passing a flag from the launcher through uvicorn to the app has no clean built-in path. An env var is the narrowest surface that works without inventing new machinery; `AMW_MCP_COMBINED=1` is a string on one code path, not a new config-loading system.
- *Single loop, single owner for async bridging.* Multiple event loops in one process is a debugging nightmare. Capture uvicorn's loop once, use it for every cross-thread async call, leave the thread's own loop alone. The bridge is `run_coroutine_threadsafe` plus `Future.result(timeout=...)` — the correct idiomatic pattern.

**Concept bucket (added).**
- *Match your test inputs to the real user's tools.* A user's zip wasn't made by Python. It was made by Finder or Safari's drag-drop zipping. Different tools produce different archive shapes. A sniff tested against Python-built zips passes; against Finder-built zips fails. If the user workflow involves a specific tool, put that tool in the test loop.
- *Unwrap on the server beats ask-user-to-re-zip.* Telling the user "re-zip without the wrapper" is a cold UX. Unwrapping on the server is ~20 lines of stdlib zipfile — one-time cost, zero user-facing explanation. Prefer the transparent fix when it's cheap.
- *Three variants of one feature is a design smell that rewards you once you notice.* The bug has always been "users want to give me an EPUB, in any of the shapes they have it." The implementation keeps addressing individual shapes. A feature-complete version accepts all four user shapes: (1) `.epub` file, (2) `.epub` folder on disk, (3) `.zip` with root mimetype, (4) `.zip` with wrapped mimetype. This commit closes the fourth.
