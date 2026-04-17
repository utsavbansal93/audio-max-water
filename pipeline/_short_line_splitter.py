"""Pair-render + VAD-split mitigation for Chatterbox's short-text artifact.

Chatterbox's diffusion sampler requires a minimum amount of input text to
stabilize. Inputs ≤10 chars (e.g. `"Hey!"`, `"Copy,"`, `"What?"`) reliably
produce gibberish — 10 consecutive retries on `"Hey!"` during Hyperthief v2.1
all produced wrong phrases (Whisper similarity ≤0.32). This is a known
Chatterbox issue: https://github.com/resemble-ai/chatterbox/issues/97

This module implements the mitigation: when a short Chatterbox line has an
adjacent same-speaker line (ignoring narrator attribution tags between them),
render BOTH texts as ONE Chatterbox call (long enough to stabilize), then use
ffmpeg `silencedetect` to find the inter-phrase pause and split the resulting
WAV into the two expected cache files.

Exposes:
    find_short_line_pairs(script, cast, short_threshold=10) -> list of SplitPair
    render_and_split_pair(pair, backend, build_dir) -> tuple[bool, str]

Integration point: `pipeline/render.py::render_chapter` calls
`find_short_line_pairs` once at the top, processes each pair (which installs
the two cache WAVs), and then the normal per-line loop finds those files and
cache-hits. Pairs where rendering or splitting fails fall back to normal
synthesis, with best-effort; per-line QA will flag them.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pipeline._cache import line_hash as _line_hash
from pipeline._ffmpeg import FFMPEG, FFPROBE
from pipeline.schema import CastModel, ChapterModel, LineModel, ScriptModel
from tts import Emotion
from tts.backend import TTSBackend


log = logging.getLogger(__name__)

_STRIP_PUNCT_RE = re.compile(r"[^\w\s]")

# Minimum alphanumeric-character count below which Chatterbox gibberishes.
# Named distinctly from validate.py's `main_threshold` (line-count concept).
SHORT_LINE_CHAR_THRESHOLD = 10


@dataclass
class SplitPair:
    """A short Chatterbox line and its pair candidate (same-speaker neighbour)."""
    chapter_number: int
    idx_short: int       # 1-based line number of the short line in its chapter
    idx_pair: int        # 1-based line number of the pair line in its chapter
    line_short: LineModel
    line_pair: LineModel
    order: str           # "short_first" (short comes before pair) or "pair_first"


def _stripped_len(text: str) -> int:
    """Count of alphanumeric + whitespace chars; ignores punctuation / quotes."""
    return len(_STRIP_PUNCT_RE.sub("", text).strip())


def find_short_line_pairs(
    script: ScriptModel,
    cast: CastModel,
    short_threshold: int = SHORT_LINE_CHAR_THRESHOLD,
    lookahead: int = 3,
    backend_name: str = "chatterbox",
) -> list[SplitPair]:
    """Return pairs suitable for render-and-split mitigation.

    A line qualifies when (a) its cast-resolved backend is `backend_name`,
    (b) its alphanumeric text length is ≤ short_threshold, and (c) it has an
    adjacent same-speaker same-backend line within `lookahead` positions
    (skipping narrator attribution tags between them). Pairs are returned in
    chapter+idx order; each short line is paired at most once.

    Typical `backend_name` is "chatterbox"; the short-text artifact is
    Chatterbox-specific in our observed data but the function is
    backend-agnostic.
    """
    pairs: list[SplitPair] = []
    used_idxs: set[tuple[int, int]] = set()  # (chapter_number, idx) already used

    # Pre-compute backend per speaker to avoid repeated cast.resolve() calls.
    speaker_backends = {
        sp: cast.resolve(sp).backend
        for sp in {line.speaker for ch in script.chapters for line in ch.lines}
        if sp in cast.mapping
    }

    for ch in script.chapters:
        for idx0, line in enumerate(ch.lines):
            idx = idx0 + 1
            if line.speaker == "narrator":
                continue
            if speaker_backends.get(line.speaker) != backend_name:
                continue
            if _stripped_len(line.text) > short_threshold:
                continue
            if (ch.number, idx) in used_idxs:
                continue

            # Look ahead past narrator tags
            pair_idx = None
            pair_line = None
            for j in range(idx0 + 1, min(len(ch.lines), idx0 + 1 + lookahead)):
                cand = ch.lines[j]
                if cand.speaker == "narrator":
                    continue
                if cand.speaker == line.speaker and speaker_backends.get(cand.speaker) == backend_name:
                    pair_idx, pair_line = j + 1, cand
                    break
                break  # different speaker → no ahead-pair

            order = "short_first"

            # Fall back to look-behind
            if pair_line is None:
                for j in range(idx0 - 1, max(idx0 - 1 - lookahead, -1), -1):
                    cand = ch.lines[j]
                    if cand.speaker == "narrator":
                        continue
                    if (cand.speaker == line.speaker
                            and speaker_backends.get(cand.speaker) == backend_name
                            and (ch.number, j + 1) not in used_idxs):
                        pair_idx, pair_line = j + 1, cand
                        order = "pair_first"
                        break
                    break

            if pair_line is None:
                continue

            pairs.append(SplitPair(
                chapter_number=ch.number,
                idx_short=idx,
                idx_pair=pair_idx,
                line_short=line,
                line_pair=pair_line,
                order=order,
            ))
            used_idxs.add((ch.number, idx))
            used_idxs.add((ch.number, pair_idx))

    return pairs


def _safe_speaker(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _expected_path(lines_dir: Path, idx: int, line: LineModel, voice_id: str, backend: str) -> Path:
    h = _line_hash(line, f"{backend}:{voice_id}")
    return lines_dir / f"{idx:04d}_{_safe_speaker(line.speaker)}_{h}.wav"


def _silence_detect(wav: Path, noise_db: int = -30, min_dur_s: float = 0.15) -> list[tuple[float, float]]:
    """Return list of (start, end) silence intervals detected by ffmpeg."""
    res = subprocess.run([
        FFMPEG, "-i", str(wav), "-af",
        f"silencedetect=noise={noise_db}dB:d={min_dur_s}", "-f", "null", "/dev/null",
    ], capture_output=True, text=True)
    intervals: list[tuple[float, float]] = []
    cur_start: Optional[float] = None
    for line in res.stderr.splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", line)
        if m:
            cur_start = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and cur_start is not None:
            intervals.append((cur_start, float(m.group(1))))
            cur_start = None
    return intervals


def _loudnorm_inplace(src: Path, lufs: int = -16, sr: int = 24000) -> None:
    """EBU R128 loudnorm via temp file → replace. Matches B4 pipeline behaviour."""
    tmp = src.with_suffix(".ln.wav")
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
        "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
        "-ar", str(sr), "-ac", "1", str(tmp),
    ], check=True)
    tmp.replace(src)


def render_and_split_pair(
    pair: SplitPair,
    backend: TTSBackend,
    backend_name: str,
    voice_id: str,
    build_dir: Path,
    *,
    max_takes: int = 4,
    sample_rate: int = 24000,
    loudness_norm: bool = True,
    noise_threshold_db: int = -30,
    min_silence_s: float = 0.15,
) -> tuple[bool, str]:
    """Render the pair's combined text, VAD-split, install two cache files.

    Returns (success, reason). On success the two target WAVs exist at the
    pipeline's expected cache paths and subsequent `render_chapter` calls
    will cache-hit them. On failure the caller should let normal per-line
    synthesis proceed.
    """
    ch_dir = build_dir / f"ch{pair.chapter_number:02d}"
    lines_dir = ch_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    first, second = (
        (pair.line_short, pair.line_pair) if pair.order == "short_first"
        else (pair.line_pair, pair.line_short)
    )
    first_idx = pair.idx_short if pair.order == "short_first" else pair.idx_pair
    second_idx = pair.idx_pair if pair.order == "short_first" else pair.idx_short

    target_first = _expected_path(lines_dir, first_idx, first, voice_id, backend_name)
    target_second = _expected_path(lines_dir, second_idx, second, voice_id, backend_name)

    # If both already cached from a previous run, skip.
    if target_first.exists() and target_second.exists():
        return True, "cache hit (no render needed)"

    combined_text = f"{first.text} {second.text}"
    emo = Emotion(**first.emotion.model_dump())  # use first line's emotion as reference

    log.info(
        "short-line pair-render: ch%02d [%s] idx %d+%d (combined %d chars)",
        pair.chapter_number, first.speaker, first_idx, second_idx, len(combined_text),
    )

    best: Optional[dict] = None
    for take in range(max_takes):
        wav_bytes, sr = backend.synthesize(
            text=combined_text, voice_id=voice_id, emotion=emo,
        )
        tmp = lines_dir / f".pair_take_{first_idx}_{take}.wav"
        tmp.write_bytes(wav_bytes)

        # Resample if needed — matches render.py's path.
        if sr != sample_rate:
            resampled = tmp.with_suffix(".rs.wav")
            subprocess.run([
                FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
                "-ar", str(sample_rate), str(resampled),
            ], check=True)
            tmp.unlink(missing_ok=True)
            resampled.rename(tmp)

        intervals = _silence_detect(tmp, noise_db=noise_threshold_db, min_dur_s=min_silence_s)
        # Total WAV duration
        dur_out = subprocess.check_output([
            FFPROBE,
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(tmp),
        ]).decode().strip()
        total = float(dur_out)

        # Pick a mid-duration silence (not near start/end)
        mid_silences = [(s, e) for s, e in intervals if 0.3 < s < total - 0.3]
        if not mid_silences:
            tmp.unlink(missing_ok=True)
            continue
        cut = sum(mid_silences[0]) / 2.0  # midpoint of the first mid-silence

        half1 = tmp.with_name(f"{tmp.stem}_h1.wav")
        half2 = tmp.with_name(f"{tmp.stem}_h2.wav")
        subprocess.run([
            FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
            "-ss", "0", "-to", f"{cut:.3f}",
            "-ar", str(sample_rate), "-ac", "1", str(half1),
        ], check=True)
        subprocess.run([
            FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
            "-ss", f"{cut:.3f}",
            "-ar", str(sample_rate), "-ac", "1", str(half2),
        ], check=True)

        # Score by half durations — both should be > 0.2s, neither should be >90% of total.
        h1_dur = _probe_duration(half1)
        h2_dur = _probe_duration(half2)
        score = 1.0
        if h1_dur < 0.2 or h2_dur < 0.2:
            score -= 0.5
        if h1_dur > 0.9 * total or h2_dur > 0.9 * total:
            score -= 0.3

        if best is None or score > best["score"]:
            if best is not None:
                for k in ("half1", "half2", "tmp"):
                    best[k].unlink(missing_ok=True)
            best = {"score": score, "half1": half1, "half2": half2, "tmp": tmp,
                    "h1_dur": h1_dur, "h2_dur": h2_dur}
        else:
            half1.unlink(missing_ok=True)
            half2.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)

        if best and best["score"] >= 0.9:
            break  # good enough, stop retrying

    if not best:
        return False, "no usable silence found in any take"

    # Install and optionally loudnorm
    shutil.move(str(best["half1"]), str(target_first))
    shutil.move(str(best["half2"]), str(target_second))
    best["tmp"].unlink(missing_ok=True)

    if loudness_norm:
        _loudnorm_inplace(target_first, sr=sample_rate)
        _loudnorm_inplace(target_second, sr=sample_rate)

    log.info(
        "  -> installed %s (%.1fs) + %s (%.1fs)",
        target_first.name, best["h1_dur"], target_second.name, best["h2_dur"],
    )
    return True, "ok"


def _probe_duration(f: Path) -> float:
    out = subprocess.check_output([
        FFPROBE,
        "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(f),
    ]).decode().strip()
    return float(out)


def render_with_appended_tail(
    line: LineModel,
    idx: int,
    chapter_number: int,
    backend: TTSBackend,
    backend_name: str,
    voice_id: str,
    build_dir: Path,
    *,
    tail: str = "That was the plan.",
    max_takes: int = 4,
    sample_rate: int = 24000,
    loudness_norm: bool = True,
    noise_threshold_db: int = -30,
    min_silence_s: float = 0.15,
) -> tuple[bool, str]:
    """Mitigation for unpaired short Chatterbox lines: render `<line.text> <tail>`,
    VAD-detect the silence between the two phrases, crop to just the first phrase.

    Tail content is discarded — it only exists to give Chatterbox enough tokens
    to stabilize. Pick a tail that naturally produces a pause before itself
    (a short declarative sentence works). The cut is at the midpoint of the
    first mid-length silence interval.
    """
    ch_dir = build_dir / f"ch{chapter_number:02d}"
    lines_dir = ch_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    target = _expected_path(lines_dir, idx, line, voice_id, backend_name)
    if target.exists():
        return True, "cache hit (no render needed)"

    combined = f"{line.text} {tail}"
    emo = Emotion(**line.emotion.model_dump())
    log.info(
        "short-line tail-append: ch%02d [%s] idx %d (combined %d chars, tail=%r)",
        chapter_number, line.speaker, idx, len(combined), tail,
    )

    best: Optional[dict] = None
    for take in range(max_takes):
        wav_bytes, sr = backend.synthesize(
            text=combined, voice_id=voice_id, emotion=emo,
        )
        tmp = lines_dir / f".tail_take_{idx}_{take}.wav"
        tmp.write_bytes(wav_bytes)
        if sr != sample_rate:
            rs = tmp.with_suffix(".rs.wav")
            subprocess.run([
                FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
                "-ar", str(sample_rate), str(rs),
            ], check=True)
            tmp.unlink(missing_ok=True)
            rs.rename(tmp)

        intervals = _silence_detect(tmp, noise_db=noise_threshold_db, min_dur_s=min_silence_s)
        total = _probe_duration(tmp)
        mid = [(s, e) for s, e in intervals if 0.3 < s < total - 0.3]
        if not mid:
            tmp.unlink(missing_ok=True)
            continue

        cut = sum(mid[0]) / 2.0
        head = tmp.with_name(f"{tmp.stem}_head.wav")
        subprocess.run([
            FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
            "-ss", "0", "-to", f"{cut:.3f}",
            "-ar", str(sample_rate), "-ac", "1", str(head),
        ], check=True)
        h_dur = _probe_duration(head)
        score = 1.0 if h_dur > 0.2 else 0.1
        if best is None or score > best["score"]:
            if best is not None:
                best["head"].unlink(missing_ok=True)
                best["tmp"].unlink(missing_ok=True)
            best = {"score": score, "head": head, "tmp": tmp, "dur": h_dur}
        else:
            head.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
        if best and best["score"] >= 0.9:
            break

    if not best:
        return False, "no mid-silence found with any tail take"

    shutil.move(str(best["head"]), str(target))
    best["tmp"].unlink(missing_ok=True)
    if loudness_norm:
        _loudnorm_inplace(target, sr=sample_rate)
    log.info("  -> installed %s (%.1fs)", target.name, best["dur"])
    return True, "ok"


def find_unpaired_short_lines(
    script: ScriptModel,
    cast: CastModel,
    short_threshold: int = SHORT_LINE_CHAR_THRESHOLD,
    lookahead: int = 3,
    backend_name: str = "chatterbox",
) -> list[tuple[int, int, LineModel]]:
    """Short Chatterbox lines with no same-speaker neighbour — candidates for
    the tail-append mitigation rather than pair-render."""
    all_pairs = find_short_line_pairs(script, cast, short_threshold, lookahead, backend_name)
    paired = {(p.chapter_number, p.idx_short) for p in all_pairs}
    paired |= {(p.chapter_number, p.idx_pair) for p in all_pairs}

    # Pre-compute backend per speaker (avoids repeated resolve() in the loop).
    speaker_backends = {
        sp: cast.resolve(sp).backend
        for sp in {line.speaker for ch in script.chapters for line in ch.lines}
        if sp in cast.mapping
    }

    out: list[tuple[int, int, LineModel]] = []
    for ch in script.chapters:
        for idx0, line in enumerate(ch.lines):
            idx = idx0 + 1
            if (ch.number, idx) in paired:
                continue
            if line.speaker == "narrator":
                continue
            if speaker_backends.get(line.speaker) != backend_name:
                continue
            if _stripped_len(line.text) > short_threshold:
                continue
            out.append((ch.number, idx, line))
    return out
