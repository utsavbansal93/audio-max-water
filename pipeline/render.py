"""Render a script.json + cast.json into per-line WAVs and a stitched chapter MP3.

Per-line WAVs are retained for surgical re-renders (see DECISIONS.md #0003).
A line is only re-synthesized if its content hash (text + voice_id + emotion)
has changed — so re-running render.py is cheap for unchanged chapters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

import yaml

from pipeline._events import ProgressCallback, ProgressEvent, emit
from pipeline.config import load_config
from pipeline.schema import CastModel, ChapterModel, LineModel, ScriptModel
from pipeline.validate import check_voice_consistency
from tts import Emotion, get_backend
from tts.backend import TTSBackend


import shutil

REPO = Path(__file__).resolve().parents[1]
CFG = load_config()
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def _line_hash(line: LineModel, voice_id: str) -> str:
    payload = json.dumps({
        "text": line.text,
        "voice": voice_id,
        "emotion": line.emotion.model_dump(),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


_TAG_STARTS = (
    "he said", "she said", "he replied", "she replied", "he added", "she added",
    "he asked", "she asked", "he whispered", "she whispered", "he answered",
    "she answered", "he muttered", "she muttered", "he continued", "she continued",
    "her companion", "his companion",
)


def _is_inline_tag(prev: LineModel | None, cur: LineModel, nxt: LineModel | None) -> bool:
    """Detect a narrator line that is a dialogue attribution tag.

    An inline tag is a short narrator line sandwiched between two dialogue
    lines of the same speaker ("he replied," between two Darcy lines). These
    should hug both sides — full speaker-change pauses make them sound
    detached from the dialogue they attribute.
    """
    if cur.speaker != "narrator":
        return False
    if prev is None or nxt is None:
        return False
    if prev.speaker == "narrator" or nxt.speaker == "narrator":
        return False
    if prev.speaker != nxt.speaker:
        return False
    text_norm = cur.text.strip().lower().rstrip(",.;:")
    # Short + starts with a known tag → treat as inline.
    if len(cur.text) <= 60 and any(text_norm.startswith(t) for t in _TAG_STARTS):
        return True
    # Even shorter fallback: very short narrator line between same-speaker
    # dialogue is almost always a tag.
    if len(cur.text) <= 30:
        return True
    return False


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
    if prev is None:
        return 0

    # Inline tag cases hug the surrounding dialogue tightly.
    if _is_inline_tag(prev, cur, nxt):
        return int(base * 0.4)
    if prev_is_inline_tag:
        return int(base * 0.4)

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

        if not wav_path.exists():
            emo = Emotion(**line.emotion.model_dump())
            wav_bytes, wav_sr = backend.synthesize(line.text, voice_id, emotion=emo)
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
        wav_paths.append(wav_path)
        prev = line

        # Emit per-line progress. Truncate the text preview so UIs aren't
        # flooded; the full script is elsewhere if they need it.
        preview = line.text[:60] + ("…" if len(line.text) > 60 else "")
        emit(on_progress, ProgressEvent(
            stage="render", phase="progress",
            message=f"ch{chapter.number:02d} line {idx}/{n_lines}: [{line.speaker}] {preview}",
            current=idx, total=n_lines,
            chapter=chapter.number, total_chapters=total_chapters,
        ))

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
