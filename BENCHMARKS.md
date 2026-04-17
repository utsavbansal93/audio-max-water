# Benchmarks

Performance record across iterations. Appended-only — every render + QA run adds a row. Enables both immediate regression detection and retrospective analysis ("when did Chapter 1 get faster?").

Columns:
- **Commit**: short SHA of the code that produced this row
- **Date**: ISO date
- **Backend**: TTS engine used
- **Target**: what was rendered (e.g., "pp_final_reconciliation ch01")
- **Lines**: number of script lines
- **Words**: total word count of script
- **Render (s)**: wall-clock time for `pipeline.render`
- **Audio (s)**: total duration of the output audio
- **RTF**: real-time factor = render / audio (lower = faster; < 1.0 means faster-than-realtime)
- **QA**: mechanical QA pass count (e.g., 16/16)
- **Whisper**: faithful-rendering similarity from `pipeline.qa --whisper` (0..1)
- **Notes**: what changed this iteration

Automated rows are appended by `pipeline/bench.py`. Manual rows are fine for one-offs.

| Commit | Date | Backend | Target | Lines | Words | Render (s) | Audio (s) | RTF | QA | Whisper | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 88d3435 | 2026-04-16 | kokoro | pp_final_reconciliation ch01 | 9 | 257 | ~30 | ~22 | ~1.36 | n/a | n/a | Initial render. Flat delivery. Cast: Emma/George/Lily. Pre-tuning. |
| fe387b6 | 2026-04-16 | kokoro | pp_final_reconciliation ch01 | 9 | 257 | ~45 | ~82 | ~0.55 | n/a | n/a | Emotion-aware pauses, wider pace range, split rhetorical beats. Cast: Isabella/Lewis/Emma. Audio grew from padding + slower pace on weighty lines. |
| fe387b6 | 2026-04-16 | kokoro | pp_final_reconciliation ch01 | 16 | 186 | 17.1 | 81.6 | 0.21 | 16/16 | 0.973 | narrator-pause fix + inline-tag detection + Kokoro slash pronunciation fix + QA pass |
| c081879 | 2026-04-16 | kokoro | pp_hunsford_proposal ch01 | 13 | 177 | 16.6 | 72.2 | 0.23 | 11/13 | 0.986 | new scene test — Darcy passionate+arrogant, Elizabeth icy lethal reply; first hearing of Elizabeth (Emma) in dialogue |
| 993b61e | 2026-04-16 | mlx-kokoro | pp_final_reconciliation ch01 | 16 | 186 | 38.0 | 81.2 | 0.47 | 16/16 | 0.989 | MLX-Kokoro backend — same weights via MLX inference path on Apple Silicon |
| 993b61e | 2026-04-16 | mlx-kokoro | pp_final_reconciliation ch01 | 16 | 186 | 12.4 | 81.2 | 0.15 | 16/16 | 0.989 | MLX-Kokoro with model loaded once in __init__ (fix per-call reload) |
| 993b61e | 2026-04-16 | mlx-kokoro | pp_hunsford_proposal ch01 | 13 | 177 | 13.7 | 71.6 | 0.19 | 12/13 | 0.992 | MLX-Kokoro on Hunsford scene |
| 723c050 | 2026-04-16 | mlx-kokoro | gatsby_west_egg_reunion ch01 | 23 | 306 | 22.2 | 125.3 | 0.18 | 23/23 | 0.985 | New book (Gatsby), new cast (Nick/Gatsby/Daisy as am_michael/am_onyx/af_heart), script-format source with stage-direction parentheticals → emotion.notes; extended validator |
| 8ec319e | 2026-04-16 | mlx-kokoro | salt_and_rust ch01 | 97 | 1401 | 3.3 | 510.3 | 0.01 | 93/97 | 0.979 | initial render — af_aoede narrator, af_nicole Furiosa, am_michael Mariner; scene_pause_ms=2000 |
| e47eb27 | 2026-04-16 | hybrid | gatsby_west_egg_reunion ch01 | 23 | 306 | 140.8 | 124.9 | 1.13 | 23/23 | 0.989 | HYBRID: narrator=Kokoro(am_michael), Gatsby+Daisy=Chatterbox w/ LibriVox Dramatic Reading refs |
| 70c2545 | 2026-04-16 | mlx-kokoro | pipeline.run first rev | 6 | 186 | 2.2 | 73.6 | 0.03 | 6/6 | skip | Phase 1 orchestrator smoke test: Gemini flash-lite parse + MLX Kokoro render + m4b + epub3 |
| 7861c2d | 2026-04-16 | mlx-kokoro | Hyperthief (full book, 6 ch) | 252 | 4670 | ~165 | 1744.2 | ~0.09 | n/a | skip | Brandon Sanderson Skyward short story → Audio-EPUB3. `script.json` hand-authored by Claude acting as the parse LLM (no Anthropic/Gemini API call); two faithful-wording divergences caught by validator and fixed before the render. 17 speakers collapsed by auto-cast to 2 Kokoro voices (af_heart / am_liam) — voice-diversity ceiling of Kokoro preset library, not a regression. |
| 8041f89 | 2026-04-17 | hybrid | Hyperthief (full book, 6 ch, re-render v2) | 334 | 4677 | ~6200 | 1741.2 | ~3.56 | n/a | skip | **Hyperthief v2** with m4b + full metadata (title/author/cover). All main characters on Chatterbox (narrator=Suzy Jackson clone from YT / FM=Daisy bright / Rig=Nick / Alanik=Jordan / Nedd=Klipspringer / Jorgen=Ch7 Police Officer). Support on 6 distinct Kokoro presets; slugs on 4 per-character presets + chorus. 43 embedded dialogue-tag lines split into 3-line sequences via new `output.inline_tag_pause_ms: 10` config + patched `_is_inline_tag` / `_is_trailing_tag` in `render.py` (DECISIONS #0035). UB Audiobooks branding prepended. Render wall-clock ~103min on M3 MBA 16GB fanless; thermal throttling ~40-50% real; parallel worker experiment NET LOSS (killed mid-render after 12-min window showed 38% regression vs main alone — MPS single-queue serialization). Script grew 253 → 334 lines (43 splits ≈ 80 new narrator attribution lines + 1 UB tag). |
| 8041f89+ | 2026-04-17 | hybrid | Hyperthief (full book, 6 ch, v2.1 rebuild) | 348 | 4677 | ~360 (rebuild only) | 1751.6 | n/a (rebuild) | n/a | skip | **Hyperthief v2.1 rebuild** after user listen-through of v2. Pronoun-based dialogue tags (`"..." he said`) split to narrator voice — 8 lines split (334 → 348 total). All 348 cached line WAVs loudnorm-equalized (EBU R128, I=-16, TP=-1.5) — post-norm peaks cluster at -1.5 dBFS (±1 dB) vs pre-norm spread of -0 to -12 dBFS. Re-render synthesized only 19 new split lines (rest cache-hit via hash-based rename). Total rebuild wall-clock ~6 min (render split lines 3min + loudnorm 36s + re-stitch 46s + package 10s). RTF n/a since most work was cache hits. Same cast as v2; same m4b metadata (cover, title, author). |
