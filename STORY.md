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
