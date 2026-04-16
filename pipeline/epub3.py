"""Audio-EPUB3 packager — EPUB3 with SMIL Media Overlays.

Produces an .epub file containing text + synchronized audio per the
EPUB 3 Media Overlays spec:
  https://www.w3.org/TR/epub-33/#sec-media-overlays

Compatible reading systems (Apple Books, Thorium, VoiceDream) highlight
each paragraph as its corresponding audio plays. The timing comes from
the per-line WAV durations already cached under `build/ch<NN>/lines/`
by `pipeline/render.py` — no extra synthesis is required.

This module writes EPUB files by hand using `zipfile` + string templates
rather than pulling in ebooklib. Ebooklib's SMIL support is thin and
the templates are short enough that a direct approach is easier to
verify against the spec.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import logging
import re
import uuid
import wave
import zipfile
from html import escape as _escape
from pathlib import Path
from typing import Optional

from pipeline._errors import PipelineError
from pipeline.schema import ChapterModel, LineModel, ScriptModel


log = logging.getLogger(__name__)


# --- low-level: timing from concat files -----------------------------------


_CONCAT_FILE_RE = re.compile(r"^file\s+'(.+)'\s*$")
_LINE_IDX_RE = re.compile(r"^(\d{4})_")


def _wav_duration_seconds(path: Path) -> float:
    with contextlib.closing(wave.open(str(path), "rb")) as w:
        frames = w.getnframes()
        rate = w.getframerate() or 1
        return frames / float(rate)


def _compute_line_times(ch_dir: Path) -> list[tuple[int, float, float]]:
    """Read the chapter's concat.txt and return [(idx, begin_s, end_s), ...]
    for each rendered line. Silence / scene-break segments count toward
    cumulative time but don't produce addressable entries.
    """
    concat_file = ch_dir / "concat.txt"
    if not concat_file.exists():
        raise PipelineError(
            f"Missing concat file for EPUB3 timing: {concat_file}. "
            "Run pipeline.render before packaging."
        )
    cursor = 0.0
    out: list[tuple[int, float, float]] = []
    for raw_line in concat_file.read_text().splitlines():
        m = _CONCAT_FILE_RE.match(raw_line.strip())
        if not m:
            continue
        wav_path = Path(m.group(1))
        if not wav_path.exists():
            raise PipelineError(f"Missing line WAV: {wav_path}")
        dur = _wav_duration_seconds(wav_path)
        name = wav_path.name
        is_gap = ("_silence_" in name) or ("_scene_break_" in name)
        if not is_gap:
            idx_match = _LINE_IDX_RE.match(name)
            if idx_match:
                idx = int(idx_match.group(1))
                out.append((idx, cursor, cursor + dur))
        cursor += dur
    return out


def _clock(seconds: float) -> str:
    """SMIL clock value: `HH:MM:SS.mmm`."""
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# --- XHTML / SMIL / OPF templates -----------------------------------------


_XHTML_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE html>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">\n'
)

_SMIL_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<smil xmlns="http://www.w3.org/ns/SMIL" '
    'xmlns:epub="http://www.idpf.org/2007/ops" version="3.0" '
    'profile="http://www.idpf.org/epub/30/profile/content/">\n'
)

_CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles>\n'
    '    <rootfile full-path="OEBPS/package.opf" '
    'media-type="application/oebps-package+xml"/>\n'
    '  </rootfiles>\n'
    '</container>\n'
)


def _render_chapter_xhtml(ch: ChapterModel) -> str:
    parts = [_XHTML_HEAD]
    parts.append(
        f"<head><meta charset=\"utf-8\"/><title>{_escape(ch.title)}</title></head>\n"
    )
    parts.append("<body>\n")
    parts.append(f"<h1 id=\"ch{ch.number:02d}_title\">{_escape(ch.title)}</h1>\n")
    for idx, line in enumerate(ch.lines, start=1):
        if line.text.strip() == "---":
            parts.append("<hr/>\n")
            continue
        parts.append(
            f'<p id="line_{idx:04d}" class="speaker-{_escape(line.speaker)}">'
            f'{_escape(line.text)}</p>\n'
        )
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def _render_chapter_smil(
    ch: ChapterModel,
    line_times: list[tuple[int, float, float]],
    xhtml_href: str,
    audio_href: str,
) -> str:
    # Index line_times by idx for direct lookup (some indices are scene breaks).
    by_idx = {idx: (b, e) for idx, b, e in line_times}
    parts = [_SMIL_HEAD, '<body>\n']
    for idx, line in enumerate(ch.lines, start=1):
        if line.text.strip() == "---":
            continue  # scene break — not addressable in SMIL
        if idx not in by_idx:
            # render.py couldn't find the line WAV; skip rather than emit
            # a <par> pointing at nothing.
            log.warning("epub3: no timing for chapter %d line %d — skipping SMIL par",
                        ch.number, idx)
            continue
        begin, end = by_idx[idx]
        parts.append(
            f'  <par id="par_{idx:04d}">\n'
            f'    <text src="{xhtml_href}#line_{idx:04d}"/>\n'
            f'    <audio src="{audio_href}" '
            f'clipBegin="{_clock(begin)}" clipEnd="{_clock(end)}"/>\n'
            f'  </par>\n'
        )
    parts.append("</body>\n</smil>\n")
    return "".join(parts)


def _render_nav_xhtml(title: str, chapters: list[ChapterModel]) -> str:
    items = "\n".join(
        f'    <li><a href="chapters/ch{ch.number:02d}.xhtml">{_escape(ch.title)}</a></li>'
        for ch in chapters
    )
    return (
        _XHTML_HEAD
        + '<head><meta charset="utf-8"/><title>Navigation</title></head>\n'
        + '<body>\n'
        + f'<h1>{_escape(title)}</h1>\n'
        + '<nav epub:type="toc" id="toc">\n'
        + f'  <h2>Contents</h2>\n'
        + '  <ol>\n'
        + items + "\n"
        + '  </ol>\n'
        + '</nav>\n'
        + '</body>\n</html>\n'
    )


def _render_opf(
    *,
    title: str,
    author: str,
    book_uuid: str,
    chapters: list[ChapterModel],
    chapter_durations_s: dict[int, float],
    total_duration_s: float,
    cover_filename: Optional[str],
) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest_items: list[str] = []
    spine_items: list[str] = []

    manifest_items.append(
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>'
    )

    if cover_filename:
        mime = "image/jpeg" if cover_filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
        manifest_items.append(
            f'    <item id="cover_img" href="{cover_filename}" '
            f'media-type="{mime}" properties="cover-image"/>'
        )

    # Chapter assets
    smil_duration_metas: list[str] = []
    for ch in chapters:
        xhtml_id = f"ch{ch.number:02d}_xhtml"
        smil_id = f"ch{ch.number:02d}_smil"
        audio_id = f"ch{ch.number:02d}_audio"
        manifest_items.append(
            f'    <item id="{xhtml_id}" href="chapters/ch{ch.number:02d}.xhtml" '
            f'media-type="application/xhtml+xml" media-overlay="{smil_id}"/>'
        )
        manifest_items.append(
            f'    <item id="{smil_id}" href="smil/ch{ch.number:02d}.smil" '
            f'media-type="application/smil+xml"/>'
        )
        manifest_items.append(
            f'    <item id="{audio_id}" href="audio/ch{ch.number:02d}.mp3" '
            f'media-type="audio/mpeg"/>'
        )
        spine_items.append(f'    <itemref idref="{xhtml_id}"/>')
        dur = chapter_durations_s.get(ch.number, 0.0)
        smil_duration_metas.append(
            f'    <meta property="media:duration" refines="#{smil_id}">'
            f'{_clock(dur)}</meta>'
        )

    duration_meta = (
        f'    <meta property="media:duration">{_clock(total_duration_s)}</meta>\n'
        + "\n".join(smil_duration_metas)
    )
    narrator_meta = (
        '    <meta property="media:active-class">-epub-media-overlay-active</meta>'
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="bookid" xml:lang="en">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">urn:uuid:{book_uuid}</dc:identifier>\n'
        f'    <dc:title>{_escape(title)}</dc:title>\n'
        f'    <dc:creator>{_escape(author)}</dc:creator>\n'
        '    <dc:language>en</dc:language>\n'
        f'    <meta property="dcterms:modified">{now}</meta>\n'
        + (f'    <meta name="cover" content="cover_img"/>\n' if cover_filename else "")
        + duration_meta + "\n"
        + narrator_meta + "\n"
        '  </metadata>\n'
        '  <manifest>\n'
        + "\n".join(manifest_items) + "\n"
        '  </manifest>\n'
        '  <spine>\n'
        + "\n".join(spine_items) + "\n"
        '  </spine>\n'
        '</package>\n'
    )


# --- entry point -----------------------------------------------------------


def build_audio_epub3(
    script_path: Path,
    chapter_mp3s: list[Path],
    out_dir: Path,
    build_dir: Path,
    title: str | None = None,
    author: str | None = None,
    cover_path: Path | None = None,
) -> Path:
    """Produce an audio-EPUB3 (.epub) with SMIL Media Overlays.

    Requires the chapter render outputs (per-line WAVs + chapter MP3s +
    concat.txt) to be present under `build_dir`. Returns the output path.
    """
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    chapters = script.chapters
    if len(chapters) != len(chapter_mp3s):
        raise ValueError(
            f"Chapter count mismatch: {len(chapters)} in script vs "
            f"{len(chapter_mp3s)} MP3s"
        )
    title = title or script.title
    author = author or "Unknown"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip().replace(" ", "_")
    out_path = out_dir / f"{safe}.epub"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-chapter timing
    line_times_by_ch: dict[int, list[tuple[int, float, float]]] = {}
    chapter_durations_s: dict[int, float] = {}
    total_s = 0.0
    for ch, mp3 in zip(chapters, chapter_mp3s):
        ch_dir = build_dir / f"ch{ch.number:02d}"
        times = _compute_line_times(ch_dir)
        line_times_by_ch[ch.number] = times
        dur = times[-1][2] if times else 0.0
        chapter_durations_s[ch.number] = dur
        total_s += dur
        log.debug("epub3: ch%02d timing — %d lines, %.1fs", ch.number, len(times), dur)

    book_uuid = str(uuid.UUID(hashlib.sha1(safe.encode()).hexdigest()[:32]))

    cover_filename: Optional[str] = None
    cover_bytes: Optional[bytes] = None
    if cover_path is not None:
        cover_bytes = Path(cover_path).read_bytes()
        ext = Path(cover_path).suffix.lower()
        cover_filename = "cover.jpg" if ext in (".jpg", ".jpeg") else "cover.png"

    log.info("epub3: writing %s (%d chapters, %.1fs audio)",
             out_path.name, len(chapters), total_s)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # `mimetype` MUST be first entry and STORED (uncompressed) per EPUB spec.
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)

        # OPF
        opf = _render_opf(
            title=title,
            author=author,
            book_uuid=book_uuid,
            chapters=chapters,
            chapter_durations_s=chapter_durations_s,
            total_duration_s=total_s,
            cover_filename=cover_filename,
        )
        zf.writestr("OEBPS/package.opf", opf)

        # Nav
        zf.writestr("OEBPS/nav.xhtml", _render_nav_xhtml(title, chapters))

        # Cover
        if cover_filename and cover_bytes is not None:
            zf.writestr(f"OEBPS/{cover_filename}", cover_bytes)

        # Per-chapter assets
        for ch, mp3 in zip(chapters, chapter_mp3s):
            xhtml = _render_chapter_xhtml(ch)
            smil = _render_chapter_smil(
                ch,
                line_times_by_ch[ch.number],
                xhtml_href=f"../chapters/ch{ch.number:02d}.xhtml",
                audio_href=f"../audio/ch{ch.number:02d}.mp3",
            )
            zf.writestr(f"OEBPS/chapters/ch{ch.number:02d}.xhtml", xhtml)
            zf.writestr(f"OEBPS/smil/ch{ch.number:02d}.smil", smil)
            zf.write(mp3, f"OEBPS/audio/ch{ch.number:02d}.mp3")

    log.info("epub3: wrote %s", out_path)
    return out_path
