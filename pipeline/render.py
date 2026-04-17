"""Render a script.json + cast.json into per-line WAVs and a stitched chapter MP3.

Per-line WAVs are retained for surgical re-renders (see DECISIONS.md #0003).
A line is only re-synthesized if its content hash (text + voice_id + emotion)
has changed — so re-running render.py is cheap for unchanged chapters.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

import yaml

from pipeline._cache import line_hash as _line_hash
from pipeline._events import ProgressCallback, ProgressEvent, emit
from pipeline._ffmpeg import FFMPEG
from pipeline._tags import text_looks_like_attribution_tag as _text_looks_like_attribution_tag
from pipeline.config import load_config
from pipeline.schema import CastModel, ChapterModel, LineModel, ScriptModel
from pipeline.validate import check_voice_consistency
from tts import Emotion, get_backend
from tts.backend import TTSBackend

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
CFG = load_config()


def _is_inline_tag(prev: LineModel | None, cur: LineModel, nxt: LineModel | None) -> bool:
    """Detect a narrator line that is a dialogue attribution tag SANDWICHED
    between two dialogue lines of the same speaker (the `"foo," Rig said, "bar"`
    pattern, once split into three lines).

    Tight pause applies on BOTH sides — the tag should hug the surrounding
    dialogue. See also `_is_trailing_tag` for tags at paragraph end.
    """
    if cur.speaker != "narrator":
        return False
    if prev is None or nxt is None:
        return False
    if prev.speaker == "narrator" or nxt.speaker == "narrator":
        return False
    if prev.speaker != nxt.speaker:
        return False
    return _text_looks_like_attribution_tag(cur.text, speaker_hint=prev.speaker)


def _is_trailing_tag(prev: LineModel | None, cur: LineModel) -> bool:
    """Detect a narrator line that is a short attribution tag following a
    character's final dialogue fragment in a paragraph (the `"foo," FM said.`
    pattern, once split).

    Tight pause applies only on the BEFORE side — the tag hugs the preceding
    dialogue. The pause AFTER falls through to normal paragraph/speaker-change
    logic since the next line crosses a paragraph boundary.
    """
    if cur.speaker != "narrator":
        return False
    if prev is None or prev.speaker == "narrator":
        return False
    return _text_looks_like_attribution_tag(cur.text, speaker_hint=prev.speaker)


def _pause_for(
    prev: LineModel | None,
    cur: LineModel,
    nxt: LineModel | None = None,
    prev_is_inline_tag: bool = False,
) -> int:
    """Silence gap in ms before `cur` line.

    Rules:
      - First line: no pause.
      - Inline dialogue tag (cur is the tag): tiny pause (0.4× base).
      - Line after an inline tag: also tiny — the dialogue should flow past.
      - Speaker change (real handoff): 2.2× base, plus emotion surcharges.
      - Same-speaker narrator→narrator: 1.2× base (prose continuity).
      - Same-speaker dialogue beats: 0.9× base (rhetorical flow).
      - Emotional peaks on either side: add held-breath / ring-out.
      - Slow pace (pace < -0.15): add approach time.
    """
    base = CFG["output"]["line_pause_ms"]
    # Explicit override for dialogue-tag gaps. Defaults to the historical
    # `int(base * 0.4)` (= 72 ms at default base=180 ms) if unset, so existing
    # stories render identically. Per-story override via build_<stem>/config.yaml
    # lets a book dial the tag tightness in without changing other pauses.
    inline_gap = CFG["output"].get("inline_tag_pause_ms", int(base * 0.4))
    if prev is None:
        return 0

    # Inline tag cases hug the surrounding dialogue tightly.
    if _is_inline_tag(prev, cur, nxt):
        return inline_gap
    if prev_is_inline_tag:
        return inline_gap
    # Trailing tag: short narrator attribution after the last dialogue fragment
    # of a paragraph. Tighten the BEFORE pause only; the AFTER pause (into the
    # next paragraph) falls through to standard paragraph/speaker logic.
    if _is_trailing_tag(prev, cur):
        return inline_gap

    speaker_change = prev.speaker != cur.speaker
    cur_int = cur.emotion.intensity
    prev_int = prev.emotion.intensity

    if speaker_change:
        gap = int(base * 2.2)
    elif cur.speaker == "narrator":
        # Narrator continuations = sentence-to-sentence prose. Needs room.
        gap = int(base * 1.2)
    else:
        # Same-speaker dialogue: rhetorical flow between fragments.
        gap = int(base * 0.9)

    # Emotional approach: held breath before a weighty line.
    if cur_int >= 0.75:
        gap += int(base * 1.4 * (cur_int - 0.5))
    # Emotional aftermath: let a weighty previous line ring out.
    if prev_int >= 0.75:
        gap += int(base * 1.0 * (prev_int - 0.5))

    # Pace < 0 means slow delivery — match it with a slightly longer approach.
    if cur.emotion.pace < -0.15:
        gap += int(base * abs(cur.emotion.pace) * 1.2)

    return gap


def _make_silence(ms: int, sr: int, path: Path) -> None:
    """Generate a silent WAV of the given duration."""
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate={sr}",
        "-t", f"{ms/1000:.3f}",
        str(path),
    ], check=True)


def _get_backend_cached(backends: dict[str, TTSBackend], name: str) -> TTSBackend:
    """Load-once backend resolution. A chapter can mix engines per speaker;
    each engine instantiates at most once regardless of how many lines it
    renders (the MLX-Kokoro lesson #0009 applied at the dispatch layer)."""
    if name not in backends:
        from tts import get_backend
        backends[name] = get_backend(name)
    return backends[name]


def render_chapter(
    backends: dict[str, TTSBackend],
    cast: CastModel,
    chapter: ChapterModel,
    build_dir: Path,
    *,
    on_progress: ProgressCallback = None,
    total_chapters: int = 0,
) -> Path:
    """Render one chapter. Returns the path to the stitched chapter MP3.

    `backends` is a mutable cache keyed by backend name; engines are loaded
    on first use so Chatterbox isn't paid for when a chapter is all-Kokoro.

    `on_progress` — optional callback fired at chapter start, per-line, and
    chapter end. None = silent (CLI default). The web UI wires this to
    an SSE event queue.
    """
    ch_dir = build_dir / f"ch{chapter.number:02d}"
    lines_dir = ch_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    sr = CFG["output"]["sample_rate"]

    # ---- Pre-synthesis pass: short-line mitigation for Chatterbox ----
    # Chatterbox reliably gibberishes on ≤10-char inputs (GitHub #97). For
    # each such line we either pair-render with an adjacent same-speaker
    # dialogue (and VAD-split) or tail-append a filler phrase (and VAD-crop).
    # Runs BEFORE the per-line loop so the main loop finds the split/cropped
    # WAVs already cached and simply uses them.
    if CFG.get("output", {}).get("short_line_mitigation", True):
        from pipeline._short_line_splitter import (
            find_short_line_pairs, find_unpaired_short_lines,
            render_and_split_pair, render_with_appended_tail,
        )
        threshold = CFG["output"].get("short_line_threshold", 10)
        # Build a tiny ScriptModel with just this chapter so the helpers work.
        from pipeline.schema import ScriptModel
        one_chapter_script = ScriptModel(
            title="", characters=[],
            chapters=[chapter],
        )
        short_pairs = find_short_line_pairs(
            one_chapter_script, cast, short_threshold=threshold, backend_name="chatterbox",
        )
        short_solo = find_unpaired_short_lines(
            one_chapter_script, cast, short_threshold=threshold, backend_name="chatterbox",
        )
        if short_pairs or short_solo:
            log.info("short-line mitigation: ch%02d — %d pair(s), %d solo",
                     chapter.number, len(short_pairs), len(short_solo))
        for p in short_pairs:
            entry = cast.resolve(p.line_short.speaker)
            be = _get_backend_cached(backends, entry.backend)
            ok, reason = render_and_split_pair(
                p, be, entry.backend, entry.voice, build_dir,
                max_takes=CFG["output"].get("short_line_max_takes", 3),
                sample_rate=sr,
                loudness_norm=CFG["output"].get("loudness_norm", True),
            )
            if not ok:
                log.warning("  pair-split failed ch%02d idx=%d+%d: %s — falling back to normal synth",
                            chapter.number, p.idx_short, p.idx_pair, reason)
        for _ch_num, idx, line in short_solo:
            entry = cast.resolve(line.speaker)
            be = _get_backend_cached(backends, entry.backend)
            ok, reason = render_with_appended_tail(
                line, idx, chapter.number, be, entry.backend, entry.voice, build_dir,
                tail=CFG["output"].get("short_line_tail", "That was the plan."),
                max_takes=CFG["output"].get("short_line_max_takes", 4),
                sample_rate=sr,
                loudness_norm=CFG["output"].get("loudness_norm", True),
            )
            if not ok:
                log.warning("  tail-append failed ch%02d idx=%d: %s — falling back to normal synth",
                            chapter.number, idx, reason)

    # Start background Whisper QA worker (CPU-bound, overlaps with MPS synthesis).
    from pipeline._qa_worker import QAWorker
    qa_worker = QAWorker(
        audit_path=build_dir / "qa_audit.jsonl",
        threshold=CFG.get("output", {}).get("qa_sim_threshold", 0.70),
        whisper_model=CFG.get("output", {}).get("qa_whisper_model", "base.en"),
    )
    qa_worker.start()

    wav_paths: list[Path] = []
    prev: LineModel | None = None
    prev_was_inline_tag = False
    lines_list = chapter.lines
    n_lines = len(lines_list)
    emit(on_progress, ProgressEvent(
        stage="render", phase="start",
        message=f"chapter {chapter.number}: {chapter.title}",
        current=0, total=n_lines,
        chapter=chapter.number, total_chapters=total_chapters,
    ))
    for idx, line in enumerate(lines_list, start=1):
        # Scene break: inject silence and skip synthesis.
        if line.text.strip() == "---":
            sil_ms = CFG["output"].get("scene_pause_ms", 1200)
            sil_path = lines_dir / f"{idx:04d}_scene_break_{sil_ms}ms.wav"
            if not sil_path.exists():
                _make_silence(sil_ms, sr, sil_path)
            wav_paths.append(sil_path)
            prev = None
            prev_was_inline_tag = False
            continue

        entry = cast.resolve(line.speaker)
        backend = _get_backend_cached(backends, entry.backend)
        voice_id = entry.voice

        # Include backend in the hash so switching engines invalidates cache
        # (same voice name can mean different things across engines).
        h = _line_hash(line, f"{entry.backend}:{voice_id}")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in line.speaker)
        wav_path = lines_dir / f"{idx:04d}_{safe_name}_{h}.wav"

        nxt = lines_list[idx] if idx < len(lines_list) else None
        pause_ms = _pause_for(prev, line, nxt, prev_is_inline_tag=prev_was_inline_tag)
        prev_was_inline_tag = _is_inline_tag(prev, line, nxt)
        if pause_ms > 0:
            silence_path = lines_dir / f"{idx:04d}_silence_{pause_ms}ms.wav"
            if not silence_path.exists():
                _make_silence(pause_ms, sr, silence_path)
            wav_paths.append(silence_path)

        cache_hit = wav_path.exists()
        took_s = 0.0
        if not cache_hit:
            emo = Emotion(**line.emotion.model_dump())
            t0 = time.perf_counter()
            chorus_on = (
                line.chorus
                and CFG.get("output", {}).get("chorus_overlay", True)
            )
            if chorus_on:
                from pipeline._chorus import render_chorus
                wav_bytes = render_chorus(
                    line, cast, backend, build_dir,
                    sample_rate=sr,
                    loudness_norm=CFG.get("output", {}).get("loudness_norm", True),
                )
                wav_sr = sr
            else:
                wav_bytes, wav_sr = backend.synthesize(line.text, voice_id, emotion=emo)
            synth_dt = time.perf_counter() - t0
            took_s = round(synth_dt, 1)
            wav_path.write_bytes(wav_bytes)
            if wav_sr != sr:
                # Resample via ffmpeg in place.
                tmp = wav_path.with_suffix(".raw.wav")
                wav_path.rename(tmp)
                subprocess.run([
                    FFMPEG, "-y", "-loglevel", "error",
                    "-i", str(tmp), "-ar", str(sr), str(wav_path),
                ], check=True)
                tmp.unlink()
            # B4: loudness-normalize so Chatterbox and Kokoro lines sit at
            # equal perceived level. See DECISIONS #0037. ~100ms/line overhead.
            if CFG.get("output", {}).get("loudness_norm", True):
                lufs = CFG["output"].get("loudness_target_lufs", -16)
                ln_tmp = wav_path.with_suffix(".ln.wav")
                subprocess.run([
                    FFMPEG, "-y", "-loglevel", "error", "-i", str(wav_path),
                    "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
                    "-ar", str(sr), "-ac", "1", str(ln_tmp),
                ], check=True)
                ln_tmp.replace(wav_path)
            # B3: per-line synthesis timing (cache-miss only; re-renders stay quiet)
            log.info("ch%02d line %d/%d: [%s] %s took %.1fs",
                     chapter.number, idx, n_lines, line.speaker, entry.backend, synth_dt)
            # Enqueue for background Whisper QA (CPU-bound; overlaps with next MPS synthesis).
            qa_worker.enqueue(wav_path, line.text, chapter.number, idx)
        wav_paths.append(wav_path)
        prev = line

        # Emit per-line progress. cache_hit + took_s let the UI render an
        # ETA and color-code cached vs fresh segments.
        preview = line.text[:60] + ("…" if len(line.text) > 60 else "")
        emit(on_progress, ProgressEvent(
            stage="render", phase="progress",
            message=f"ch{chapter.number:02d} line {idx}/{n_lines}: [{line.speaker}] {preview}",
            current=idx, total=n_lines,
            chapter=chapter.number, total_chapters=total_chapters,
            extra={"cache_hit": cache_hit, "took_s": took_s,
                   "speaker": line.speaker, "text_preview": preview},
        ))

    qa_worker.stop()

    # Stitch via ffmpeg concat.
    concat_file = ch_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{p.resolve()}'" for p in wav_paths) + "\n")
    out_mp3 = ch_dir / f"chapter_{chapter.number:02d}.mp3"
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-ac", "1", "-ar", str(sr), "-b:a", "128k",
        str(out_mp3),
    ], check=True)
    return out_mp3


def render_all(
    script_path: Path,
    cast_path: Path,
    backend_name: str | None = None,
    build_dir: Path | None = None,
    *,
    on_progress: ProgressCallback = None,
    backends: dict[str, TTSBackend] | None = None,
) -> list[Path]:
    global CFG
    render_start_t = time.perf_counter()
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    cast = CastModel.model_validate(json.loads(cast_path.read_text()))
    build_dir = build_dir or (REPO / "build")

    # Load per-story config overrides (e.g. build_salt_and_rust/config.yaml).
    # Deep-merges <build_dir>/config.yaml over global config.yaml when present.
    CFG = load_config(build_dir)

    # Backend resolution order for BARE-STRING cast entries (legacy):
    # explicit arg > config.yaml > cast.json. Entries of form
    # {"voice":..., "backend":...} carry their own backend and ignore this.
    default_backend = backend_name or CFG.get("backend") or cast.backend

    # Patch the cast's default backend so resolve() uses our override for
    # bare-string entries without mutating cast.json on disk.
    cast = cast.model_copy(update={"backend": default_backend})

    # B6: acquire render lock (one render per build dir; one Chatterbox
    # render machine-wide). Fails fast with ConfigurationError if another
    # render is already holding the lock.
    speakers_all = {line.speaker for ch in script.chapters for line in ch.lines}
    uses_chatterbox = any(
        cast.resolve(sp).backend == "chatterbox"
        for sp in speakers_all if sp in cast.mapping
    )
    from pipeline._memory import acquire_render_lock
    acquire_render_lock(build_dir, chatterbox=uses_chatterbox)

    # B7: hardware snapshot at start-of-render. Never raises.
    from pipeline._hardware import write_hardware_snapshot
    write_hardware_snapshot(build_dir, phase="start")

    # Validate: every speaker in the script must have a cast entry, and every
    # voice id must exist in the backend that will render it. We check
    # voice-id validity per-backend by loading each backend on-demand just
    # for list_voices() — same cache the renderer uses.
    #
    # If `backends` was supplied by the caller (UI passes its shared pool),
    # reuse those instances so MLX / Chatterbox aren't loaded twice in one
    # process.
    if backends is None:
        backends = {}
    speakers = {line.speaker for ch in script.chapters for line in ch.lines}
    voice_errs: list[str] = []
    for sp in speakers:
        if sp not in cast.mapping:
            voice_errs.append(f"Speaker {sp!r} missing from cast.json")
            continue
        entry = cast.resolve(sp)
        b = _get_backend_cached(backends, entry.backend)
        if entry.voice not in {v.id for v in b.list_voices()}:
            voice_errs.append(
                f"Cast {sp!r} -> {entry.voice!r} is not a valid voice id "
                f"for backend {entry.backend!r}"
            )
    if voice_errs:
        for e in voice_errs:
            print("ERROR:", e)
        raise SystemExit(1)

    # B2: main-character voice-uniqueness check. Fails the render if ≥2
    # speakers with ≥threshold lines share the same (backend, voice_id).
    from pipeline.validate import check_main_character_voice_uniqueness
    from pipeline._errors import ConfigurationError
    threshold = CFG.get("validation", {}).get("main_character_threshold", 10)
    uniq_errs = check_main_character_voice_uniqueness(script, cast, threshold)
    if uniq_errs:
        raise ConfigurationError(
            "Main characters must have distinct voices:\n  " + "\n  ".join(uniq_errs),
            fix="Edit cast.json — assign each main character a unique voice preset. "
                "When Kokoro presets exhaust, use Chatterbox + a reference clip in voice_samples/.",
        )

    outputs: list[Path] = []
    total = len(script.chapters)
    for ch in script.chapters:
        print(f"rendering chapter {ch.number}: {ch.title}")
        out = render_chapter(
            backends, cast, ch, build_dir,
            on_progress=on_progress, total_chapters=total,
        )
        print("  ->", out)
        outputs.append(out)
        emit(on_progress, ProgressEvent(
            stage="render", phase="done",
            message=f"chapter {ch.number} done",
            current=ch.number, total=total,
            chapter=ch.number, total_chapters=total,
        ))

    # B7: end-of-render hardware snapshot. Records peak RSS + wall-clock
    # alongside the cpu/ram/thermal readout. Best-effort; never raises.
    try:
        import psutil
        peak_rss_mb = psutil.Process().memory_info().rss / 1024**2
    except Exception:
        peak_rss_mb = None
    write_hardware_snapshot(
        build_dir, phase="end",
        extras={
            "wall_clock_s": round(time.perf_counter() - render_start_t, 1),
            "peak_rss_mb": round(peak_rss_mb, 1) if peak_rss_mb else None,
            "chapters_rendered": len(outputs),
        },
    )
    return outputs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script",  default="build/script.json", type=Path)
    ap.add_argument("--cast",    default="cast.json",         type=Path)
    ap.add_argument("--backend", default=None, help="Override cast.json backend")
    ap.add_argument("--build",   default="build",             type=Path)
    args = ap.parse_args()

    # Memory watchdog: refuse to start if the machine can't safely hold the
    # models this render will load. See pipeline/_memory.py and CLAUDE.md.
    from pipeline._memory import require_free
    _cfg_backend = args.backend or CFG.get("backend")
    require_free(min_gb=4.0, backend=_cfg_backend)

    render_all(args.script, args.cast, args.backend, args.build)


if __name__ == "__main__":
    main()
