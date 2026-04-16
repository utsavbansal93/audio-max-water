"""Package chapter MP3s into a distributable audiobook artifact.

Two output formats:
  - m4b  — MPEG-4 Audio Book (AAC + chapter markers + optional cover art).
  - epub3 — EPUB3 with SMIL Media Overlays (synced text + audio). Delegates
    to `pipeline.epub3.build_audio_epub3` for the actual packaging.

The `package()` dispatcher is the single entry point used by
`pipeline.run`; the `build_m4b()` / `build_audio_epub3()` functions stay
directly callable for tests and ad-hoc use.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import yaml

from pipeline.schema import ScriptModel


REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

OutputFormat = Literal["m4b", "epub3"]


def _duration_ms(path: Path) -> int:
    out = subprocess.check_output([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]).decode().strip()
    return int(float(out) * 1000)


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip().replace(" ", "_")


# Minimal ISO-639-1 → ISO-639-2 mapping for m4b metadata. Covers the
# most common cases we'll see in audiobook sources; unknown codes pass
# through so they're still set (ffmpeg will tolerate arbitrary 3-letter).
_ISO_LANG_MAP = {
    "en": "eng", "fr": "fre", "de": "ger", "es": "spa", "it": "ita",
    "pt": "por", "ru": "rus", "zh": "zho", "ja": "jpn", "ko": "kor",
    "ar": "ara", "hi": "hin", "nl": "dut", "pl": "pol", "sv": "swe",
    "tr": "tur",
}


def _iso639_2(lang: str) -> str:
    code = (lang or "en").split("-")[0].split("_")[0].strip().lower()
    return _ISO_LANG_MAP.get(code, code if len(code) == 3 else "eng")


def build_m4b(
    script_path: Path,
    chapter_mp3s: list[Path],
    out_dir: Path,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
    cover_path: Path | None = None,
) -> Path:
    """Build an .m4b from stitched chapter MP3s.

    If `cover_path` is provided, embed the image as an `attached_pic`
    video stream — the m4b cover convention that Apple Books / Plex /
    VLC all respect.
    """
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    chapters = script.chapters
    if len(chapters) != len(chapter_mp3s):
        raise ValueError(
            f"Chapter count mismatch: {len(chapters)} in script vs "
            f"{len(chapter_mp3s)} MP3s"
        )
    if cover_path is not None and not Path(cover_path).exists():
        raise FileNotFoundError(f"Cover image not found: {cover_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    title = title or script.title
    out_m4b = out_dir / f"{_safe_filename(title)}.m4b"

    # 1. Concat file for chapter MP3s.
    concat_file = out_dir / "_concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in chapter_mp3s) + "\n"
    )

    # 2. FFMETADATA1 with chapter markers. Language uses ffmpeg's
    # iso-639-2 3-letter code where possible (e.g. "eng" for "en").
    ffmeta = [";FFMETADATA1", f"title={title}"]
    if author:
        ffmeta.append(f"artist={author}")
        ffmeta.append(f"album_artist={author}")  # audiobook convention
    ffmeta.append(f"language={_iso639_2(language)}")
    ffmeta.append("genre=Audiobook")
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

    # 3. ffmpeg command — base audio + metadata, with optional cover input.
    bitrate = CFG["output"]["m4b_bitrate"]
    cmd: list[str] = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(ffmeta_path),
    ]
    if cover_path is not None:
        cmd += ["-i", str(cover_path)]

    cmd += [
        "-map", "0:a",
        "-map_metadata", "1",
    ]
    if cover_path is not None:
        # Cover art is a single MJPEG frame marked as attached_pic so players
        # treat it as cover art, not a video stream.
        cmd += [
            "-map", "2:v",
            "-c:v", "mjpeg",
            "-disposition:v", "attached_pic",
        ]
    cmd += [
        "-c:a", "aac", "-b:a", bitrate,
        "-ac", "1",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(out_m4b),
    ]
    subprocess.run(cmd, check=True)

    # Cleanup temp files.
    concat_file.unlink()
    ffmeta_path.unlink()
    return out_m4b


def package(
    script_path: Path,
    chapter_mp3s: list[Path],
    out_dir: Path,
    *,
    format: OutputFormat = "m4b",
    build_dir: Path | None = None,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
    cover_path: Path | None = None,
) -> Path:
    """Dispatch to the selected output format.

    `build_dir` is required for epub3 (needed to locate per-line WAVs
    whose durations drive the SMIL clipBegin/clipEnd timings) and
    unused for m4b. Kept optional to preserve the m4b-default CLI.
    """
    if format == "m4b":
        return build_m4b(
            script_path=script_path,
            chapter_mp3s=chapter_mp3s,
            out_dir=out_dir,
            title=title,
            author=author,
            language=language,
            cover_path=cover_path,
        )
    if format == "epub3":
        if build_dir is None:
            raise ValueError(
                "epub3 packaging needs --build to locate per-line WAVs for "
                "SMIL timing. Pass build_dir to package()."
            )
        from pipeline.epub3 import build_audio_epub3
        return build_audio_epub3(
            script_path=script_path,
            chapter_mp3s=chapter_mp3s,
            out_dir=out_dir,
            build_dir=build_dir,
            title=title,
            author=author,
            language=language,
            cover_path=cover_path,
        )
    raise ValueError(f"Unknown output format: {format!r}. Known: m4b, epub3")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build",  default="build",  type=Path)
    ap.add_argument("--out",    default="out",    type=Path)
    ap.add_argument("--title",  default=None)
    ap.add_argument("--author", default=None)
    ap.add_argument("--cover",  default=None, type=Path,
                    help="Optional cover image (JPG/PNG); embedded in output")
    ap.add_argument("--format", default="m4b", choices=["m4b", "epub3"],
                    help="Output format (default: m4b)")
    ap.add_argument("--script", default=None, type=Path,
                    help="Default: <build>/script.json")
    args = ap.parse_args()

    script_path = args.script or (args.build / "script.json")
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    chapter_mp3s = [args.build / f"ch{ch.number:02d}" / f"chapter_{ch.number:02d}.mp3"
                    for ch in script.chapters]
    missing = [p for p in chapter_mp3s if not p.exists()]
    if missing:
        raise SystemExit(f"Missing chapter MP3s: {missing}. Run pipeline.render first.")

    out = package(
        script_path=script_path,
        chapter_mp3s=chapter_mp3s,
        out_dir=args.out,
        format=args.format,
        build_dir=args.build,
        title=args.title,
        author=args.author,
        cover_path=args.cover,
    )
    print("wrote", out)


if __name__ == "__main__":
    main()
