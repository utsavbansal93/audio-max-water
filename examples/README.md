# Examples

Three short `.m4b` samples that show what the pipeline produces without any configuration beyond what ships in the repo. Open any of them in Apple Books, Books.app, VLC, or anything that plays `.m4b` / MP4 audio.

## `pp_reconciliation_sample.m4b` · 82 s · Kokoro British cast

**Source.** Jane Austen, *Pride and Prejudice*, Chapter 58 — the walk at Longbourn where Darcy proposes again, this time successfully. Prose-format source at [`stories/pp_final_reconciliation.md`](../stories/pp_final_reconciliation.md).

**Cast.**
- Narrator → `bf_isabella` (Kokoro British female, refined)
- Darcy → `bm_lewis` (Kokoro British male, deep/thoughtful)
- Elizabeth → `bf_emma` (Kokoro British female, warm)

**What this demonstrates.** The default zero-touch path — no voice cloning, no reference clips. Kokoro's British voice presets have enough prosodic range to carry Austen's register; emotion is implied through script-level intensity + pace + silence, not through an engine emotion knob.

## `pp_hunsford_sample.m4b` · 72 s · Kokoro British cast

**Source.** Same book, Chapter 34 — Darcy's disastrous first proposal and Elizabeth's cold, lethal reply. Prose-format source at [`stories/pp_hunsford_proposal.md`](../stories/pp_hunsford_proposal.md).

**Cast.** Identical to the reconciliation sample. Reads from the same [`cast.json`](../cast.json).

**What this demonstrates.** **Cross-scene voice consistency.** The same actors inhabit the same characters across two different scenes from the same book with no re-casting. `cast.json` is the single source of truth; swapping scenes doesn't perturb voices. The tonal inversion (ice where the other scene has warmth) is entirely in the script's emotion annotations, not the voices.

## `gatsby_west_egg_sample.m4b` · 125 s · Hybrid engine

**Source.** F. Scott Fitzgerald, *The Great Gatsby*, Chapter 5 — the West Egg reunion, when Gatsby and Daisy meet after five years. Script-format source at [`stories/gatsby_west_egg_reunion.md`](../stories/gatsby_west_egg_reunion.md) (uses `Narrator:` / `Gatsby:` labels and `(stage direction)` parentheticals).

**Cast (hybrid engine — see [`cast_gatsby.json`](../cast_gatsby.json)).**
- Narrator (Nick Carraway) → `am_michael` on **Kokoro** (fast, fine for prose narration)
- Gatsby → reference clip on **Chatterbox** — voice cloned from Tomas Peter's performance in the LibriVox Version 5 Dramatic Reading, extracted from Chapter 5 at 1083.8–1091.7 s.
- Daisy → reference clip on **Chatterbox** — voice cloned from Jasmin Salma's performance in the same LibriVox reading, from the shirts scene at 1343.5–1352.8 s.

**What this demonstrates.** **Per-character backend assignment.** When Kokoro's voice library isn't emotional enough for a character — as with Gatsby and Daisy in this scene — the pipeline drops those characters onto Chatterbox (autoregressive, exaggeration-slider) while keeping the narrator on Kokoro (fast, deterministic). Reference audio sourced from public-domain LibriVox recordings; full attribution and extraction methodology in [`voice_samples/SOURCES.md`](../voice_samples/SOURCES.md).

**What to listen for.**
1. Gatsby's *"It's stopped."* — the scene's emotional low. The Chatterbox voice carries the held breath.
2. Daisy's *"You're sure you want us to come?"* — the tender turn. Jasmin Salma's shirts-scene reference makes her sound as if she's already close to tears.
3. Gatsby's *"Absolutely. I keep it full of interesting people…"* — the pivot to radiant-salesman mode. Same voice, opposite register.

## Try it yourself

```bash
git clone https://github.com/utsavbansal93/audio-max-water
cd audio-max-water
brew install python@3.12 ffmpeg espeak-ng
python3.12 -m venv .venv && .venv/bin/pip install -e .

# Re-render the P&P samples (Kokoro only):
.venv/bin/python -m pipeline.bench \
    --script build/script.json --cast cast.json --build build \
    --target "pp ch58" --notes "reproducing the example"

# For the hybrid Gatsby sample you also need chatterbox:
.venv/bin/pip install chatterbox-tts
.venv/bin/python -m pipeline.bench \
    --script build_gatsby/script.json --cast cast_gatsby.json --build build_gatsby \
    --target "gatsby ch05" --notes "reproducing the hybrid example"
```

See the main [`README.md`](../README.md) for full docs.
