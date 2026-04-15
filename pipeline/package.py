"""Package chapter MP3s into a single .m4b with chapter markers."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

from pipeline.schema import ScriptModel


REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"


def _duration_ms(path: Path) -> int:
    out = subprocess.check_output([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]).decode().strip()
    return int(float(out) * 1000)


def build_m4b(
    script_path: Path,
    chapter_mp3s: list[Path],
    out_dir: Path,
    title: str | None = None,
) -> Path:
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    chapters = script.chapters
    if len(chapters) != len(chapter_mp3s):
        raise ValueError(f"Chapter count mismatch: {len(chapters)} in script vs {len(chapter_mp3s)} MP3s")

    out_dir.mkdir(parents=True, exist_ok=True)
    title = title or script.title
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip().replace(" ", "_")
    out_m4b = out_dir / f"{safe_name}.m4b"

    # 1. Concatenate all MP3s into one AAC stream.
    concat_file = out_dir / "_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.resolve()}'" for p in chapter_mp3s) + "\n")

    # 2. Build ffmetadata with chapter markers.
    ffmeta = [";FFMETADATA1", f"title={title}"]
    cursor = 0
    for ch, mp3 in zip(chapters, chapter_mp3s):
        dur = _duration_ms(mp3)
        ffmeta += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={cursor}",
            f"END={cursor + dur}",
            f"title={ch.title}",
        ]
        cursor += dur
    ffmeta_path = out_dir / "_chapters.ffmeta"
    ffmeta_path.write_text("\n".join(ffmeta) + "\n")

    # 3. Run ffmpeg: concat + metadata + AAC + m4b container.
    bitrate = CFG["output"]["m4b_bitrate"]
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(ffmeta_path),
        "-map_metadata", "1",
        "-c:a", "aac", "-b:a", bitrate,
        "-ac", "1",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(out_m4b),
    ], check=True)

    # Cleanup temp files.
    concat_file.unlink()
    ffmeta_path.unlink()
    return out_m4b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="build/script.json", type=Path)
    ap.add_argument("--build",  default="build",             type=Path)
    ap.add_argument("--out",    default="out",               type=Path)
    ap.add_argument("--title",  default=None)
    args = ap.parse_args()

    script = ScriptModel.model_validate(json.loads(args.script.read_text()))
    chapter_mp3s = [args.build / f"ch{ch.number:02d}" / f"chapter_{ch.number:02d}.mp3" for ch in script.chapters]
    missing = [p for p in chapter_mp3s if not p.exists()]
    if missing:
        raise SystemExit(f"Missing chapter MP3s: {missing}. Run pipeline.render first.")
    out = build_m4b(args.script, chapter_mp3s, args.out, args.title)
    print("wrote", out)


if __name__ == "__main__":
    main()
