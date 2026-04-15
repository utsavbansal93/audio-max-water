"""Render + QA + append a row to BENCHMARKS.md.

Usage:
    python -m pipeline.bench --target "pp_final_reconciliation ch01" \
                             --notes "short description of what changed"
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import soundfile as sf

from pipeline.qa import scan_chapter, whisper_roundtrip
from pipeline.render import render_all
from pipeline.schema import ScriptModel


import shutil

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "BENCHMARKS.md"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def _git_sha_short() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"], cwd=REPO
        ).decode().strip()
    except Exception:
        return "uncommitted"


def _audio_dur_s(mp3: Path) -> float:
    out = subprocess.check_output([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(mp3),
    ]).decode().strip()
    return float(out)


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _append_row(row: dict) -> None:
    line = "| " + " | ".join(str(row[k]) for k in [
        "commit", "date", "backend", "target", "lines", "words",
        "render_s", "audio_s", "rtf", "qa", "whisper", "notes",
    ]) + " |\n"
    with BENCH.open("a") as f:
        f.write(line)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="build/script.json", type=Path)
    ap.add_argument("--cast",   default="cast.json", type=Path)
    ap.add_argument("--build",  default="build", type=Path)
    ap.add_argument("--target", required=True,
                    help="Short label for the BENCHMARKS row, e.g. 'pp_final_reconciliation ch01'")
    ap.add_argument("--notes",  required=True,
                    help="What changed this iteration (few words)")
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--chapter", type=int, default=1)
    args = ap.parse_args()

    script = ScriptModel.model_validate(json.loads(args.script.read_text()))
    chapter = next(c for c in script.chapters if c.number == args.chapter)
    n_lines = len(chapter.lines)
    n_words = sum(_word_count(line.text) for line in chapter.lines)

    t0 = time.perf_counter()
    outputs = render_all(args.script, args.cast, build_dir=args.build)
    render_s = time.perf_counter() - t0

    chapter_mp3 = args.build / f"ch{args.chapter:02d}" / f"chapter_{args.chapter:02d}.mp3"
    audio_s = _audio_dur_s(chapter_mp3)
    rtf = render_s / audio_s if audio_s else float("nan")

    qa_results = scan_chapter(args.script, args.chapter, args.build)
    qa_pass = sum(1 for r in qa_results if r.ok())
    qa_col = f"{qa_pass}/{len(qa_results)}"

    whisper_col = "skip"
    if not args.no_whisper:
        expected = " ".join(line.text for line in chapter.lines)
        ratio, _div = whisper_roundtrip(chapter_mp3, expected)
        whisper_col = f"{ratio:.3f}"

    import yaml
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())

    row = {
        "commit":   _git_sha_short(),
        "date":     time.strftime("%Y-%m-%d"),
        "backend":  cfg["backend"],
        "target":   args.target,
        "lines":    n_lines,
        "words":    n_words,
        "render_s": f"{render_s:.1f}",
        "audio_s":  f"{audio_s:.1f}",
        "rtf":      f"{rtf:.2f}",
        "qa":       qa_col,
        "whisper":  whisper_col,
        "notes":    args.notes,
    }
    _append_row(row)
    print("appended to BENCHMARKS.md:")
    for k, v in row.items():
        print(f"  {k:<9} {v}")


if __name__ == "__main__":
    main()
