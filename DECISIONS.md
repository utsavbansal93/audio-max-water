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
