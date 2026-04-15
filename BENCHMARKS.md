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
| 8ec319e | 2026-04-16 | mlx-kokoro | gatsby_west_egg_reunion ch01 | 23 | 306 | 140.8 | 124.9 | 1.13 | 23/23 | 0.989 | HYBRID: narrator=Kokoro(am_michael), Gatsby+Daisy=Chatterbox with LibriVox Dramatic Reading refs |
