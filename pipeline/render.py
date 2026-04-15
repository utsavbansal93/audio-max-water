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

from pipeline.schema import CastModel, ChapterModel, LineModel, ScriptModel
from pipeline.validate import check_voice_consistency
from tts import Emotion, get_backend
from tts.backend import TTSBackend


REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
FFMPEG = "/opt/homebrew/bin/ffmpeg"


def _line_hash(line: LineModel, voice_id: str) -> str:
    payload = json.dumps({
        "text": line.text,
        "voice": voice_id,
        "emotion": line.emotion.model_dump(),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def _pause_for(prev: LineModel | None, cur: LineModel) -> int:
    """Silence gap in ms before `cur` line."""
    if prev is None:
        return 0
    # Paragraph / scene detection could live here; for v1, use line-level pause.
    return CFG["output"]["line_pause_ms"]


def _make_silence(ms: int, sr: int, path: Path) -> None:
    """Generate a silent WAV of the given duration."""
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate={sr}",
        "-t", f"{ms/1000:.3f}",
        str(path),
    ], check=True)


def render_chapter(
    backend: TTSBackend,
    cast: CastModel,
    chapter: ChapterModel,
    build_dir: Path,
) -> Path:
    """Render one chapter. Returns the path to the stitched chapter MP3."""
    ch_dir = build_dir / f"ch{chapter.number:02d}"
    lines_dir = ch_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    sr = CFG["output"]["sample_rate"]

    wav_paths: list[Path] = []
    prev: LineModel | None = None
    for idx, line in enumerate(chapter.lines, start=1):
        voice_id = cast.mapping[line.speaker]
        h = _line_hash(line, voice_id)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in line.speaker)
        wav_path = lines_dir / f"{idx:04d}_{safe_name}_{h}.wav"

        pause_ms = _pause_for(prev, line)
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
) -> list[Path]:
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    cast = CastModel.model_validate(json.loads(cast_path.read_text()))
    build_dir = build_dir or (REPO / "build")

    backend_name = backend_name or cast.backend
    backend = get_backend(backend_name)

    errs = check_voice_consistency(script, cast, {v.id for v in backend.list_voices()})
    if errs:
        for e in errs:
            print("ERROR:", e)
        raise SystemExit(1)

    outputs: list[Path] = []
    for ch in script.chapters:
        print(f"rendering chapter {ch.number}: {ch.title}")
        out = render_chapter(backend, cast, ch, build_dir)
        print("  ->", out)
        outputs.append(out)
    return outputs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script",  default="build/script.json", type=Path)
    ap.add_argument("--cast",    default="cast.json",         type=Path)
    ap.add_argument("--backend", default=None, help="Override cast.json backend")
    ap.add_argument("--build",   default="build",             type=Path)
    args = ap.parse_args()
    render_all(args.script, args.cast, args.backend, args.build)


if __name__ == "__main__":
    main()
