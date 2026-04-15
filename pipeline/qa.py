"""Mechanical audio QA + Whisper round-trip.

This is NOT "does it sound good" — I can't listen. It catches cheap, objective
defects that would force a re-render: wrong duration for the line length,
clipping, dropouts, silent clips, wildly inconsistent loudness across voices,
and (via Whisper) transcription drift from the scripted text.

Run:
    python -m pipeline.qa build/script.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from pipeline.schema import ScriptModel


import shutil

REPO = Path(__file__).resolve().parents[1]
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


# --- thresholds (deliberately loose — we want regressions, not perfectionism) -

# Words per second: natural English narration is 2.3–3.0; Kokoro at slow pace ~2.0.
WPS_LOW  = 1.3
WPS_HIGH = 5.0
# Peak dB: anything > -1 dB is almost-clipping.
PEAK_DB_MAX = -1.0
# RMS dB: quiet audiobook target roughly -18..-23 dBFS.
RMS_DB_LOW  = -32.0
RMS_DB_HIGH = -10.0
# Silent-clip detection: RMS below this over the whole clip = broken.
RMS_DB_SILENT = -50.0


@dataclass
class LineQA:
    idx: int
    speaker: str
    text: str
    wav: Path
    dur_ms: int
    words: int
    wps: float
    peak_db: float
    rms_db: float
    issues: list[str]

    def ok(self) -> bool:
        return not self.issues


def _audio_stats(wav: Path) -> tuple[int, float, float]:
    """Return (duration_ms, peak_dBFS, rms_dBFS)."""
    data, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.size == 0:
        return 0, -120.0, -120.0
    peak = float(np.max(np.abs(data)))
    rms = float(np.sqrt(np.mean(data ** 2)))
    peak_db = 20 * np.log10(peak + 1e-12)
    rms_db = 20 * np.log10(rms + 1e-12)
    dur_ms = int(1000 * data.size / sr)
    return dur_ms, peak_db, rms_db


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def scan_chapter(script_path: Path, chapter_number: int, build_dir: Path) -> list[LineQA]:
    script = ScriptModel.model_validate(json.loads(script_path.read_text()))
    chapter = next(c for c in script.chapters if c.number == chapter_number)
    ch_dir = build_dir / f"ch{chapter_number:02d}" / "lines"

    # Find rendered WAVs (not silence files). Match by index prefix.
    wavs_by_idx: dict[int, Path] = {}
    for p in sorted(ch_dir.glob("*.wav")):
        m = re.match(r"^(\d{4})_(?!silence_)", p.name)
        if m:
            wavs_by_idx[int(m.group(1))] = p

    # Per-voice RMS statistics so we can flag loudness outliers.
    by_voice: dict[str, list[float]] = {}
    results: list[LineQA] = []

    for idx, line in enumerate(chapter.lines, start=1):
        wav = wavs_by_idx.get(idx)
        issues: list[str] = []
        if wav is None:
            issues.append("no rendered WAV found")
            results.append(LineQA(idx, line.speaker, line.text, Path(), 0, _word_count(line.text), 0.0, -120, -120, issues))
            continue

        dur_ms, peak_db, rms_db = _audio_stats(wav)
        words = _word_count(line.text)
        wps = (words * 1000 / dur_ms) if dur_ms else 0.0

        if dur_ms < 150:
            issues.append(f"suspiciously short ({dur_ms} ms)")
        if peak_db > PEAK_DB_MAX:
            issues.append(f"peak {peak_db:.1f} dB — near clipping")
        if rms_db < RMS_DB_SILENT:
            issues.append(f"RMS {rms_db:.1f} dB — effectively silent")
        elif not (RMS_DB_LOW <= rms_db <= RMS_DB_HIGH):
            issues.append(f"RMS {rms_db:.1f} dB outside typical audiobook range [{RMS_DB_LOW}, {RMS_DB_HIGH}]")
        if words > 2 and not (WPS_LOW <= wps <= WPS_HIGH):
            issues.append(f"pacing {wps:.2f} words/sec outside [{WPS_LOW}, {WPS_HIGH}]")

        by_voice.setdefault(line.speaker, []).append(rms_db)
        results.append(LineQA(idx, line.speaker, line.text, wav, dur_ms, words, wps, peak_db, rms_db, issues))

    # Loudness consistency per voice: flag lines > 4 dB off the voice's median.
    for speaker, rms_list in by_voice.items():
        median = float(np.median(rms_list))
        for r in results:
            if r.speaker != speaker or not r.wav.exists():
                continue
            if abs(r.rms_db - median) > 4.0:
                r.issues.append(f"RMS {r.rms_db:.1f} dB differs {r.rms_db - median:+.1f} dB from {speaker} median")
    return results


def print_report(results: list[LineQA]) -> int:
    """Return non-zero if any issues found."""
    total = len(results)
    failing = [r for r in results if not r.ok()]
    print(f"QA: {total - len(failing)}/{total} lines OK")
    for r in results:
        tag = "OK" if r.ok() else "!! "
        snippet = r.text[:55] + ("…" if len(r.text) > 55 else "")
        print(f"  {tag:<3} line {r.idx:02d} [{r.speaker:<9}] {r.dur_ms:>5} ms  {r.wps:>4.2f} w/s  peak {r.peak_db:>5.1f}  rms {r.rms_db:>5.1f}  |  {snippet}")
        for iss in r.issues:
            print(f"         - {iss}")
    return len(failing)


# --- Whisper round-trip -------------------------------------------------------

def whisper_roundtrip(chapter_mp3: Path, expected_text: str, model_name: str = "base.en") -> tuple[float, list[str]]:
    """Transcribe chapter audio and diff against expected text.

    Returns (similarity_ratio, divergence_snippets). Similarity ratio is
    difflib's SequenceMatcher on normalized lowercase word streams —
    0.0 = nothing matches, 1.0 = identical.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("faster-whisper not installed. Run: .venv/bin/pip install faster-whisper") from e

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(chapter_mp3), beam_size=1, language="en")
    heard = " ".join(s.text.strip() for s in segments)

    def norm(s: str) -> list[str]:
        s = re.sub(r"[^\w\s]", " ", s.lower())
        return s.split()
    hw = norm(heard)
    ew = norm(expected_text)
    ratio = difflib.SequenceMatcher(None, ew, hw).ratio()

    # Surface first divergence.
    divergences: list[str] = []
    matcher = difflib.SequenceMatcher(None, ew, hw)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        ctx_e = " ".join(ew[max(0, i1 - 4): i2 + 4])
        ctx_h = " ".join(hw[max(0, j1 - 4): j2 + 4])
        divergences.append(f"  expected: ...{ctx_e}...\n  heard:    ...{ctx_h}...")
        if len(divergences) >= 3:
            break
    return ratio, divergences


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="build/script.json", type=Path)
    ap.add_argument("--chapter", type=int, default=1)
    ap.add_argument("--build",   default="build", type=Path)
    ap.add_argument("--whisper", action="store_true", help="Run Whisper round-trip on chapter MP3")
    ap.add_argument("--whisper-model", default="base.en")
    args = ap.parse_args()

    results = scan_chapter(args.script, args.chapter, args.build)
    n_failing = print_report(results)

    if args.whisper:
        mp3 = args.build / f"ch{args.chapter:02d}" / f"chapter_{args.chapter:02d}.mp3"
        if not mp3.exists():
            print(f"\nWhisper skipped: {mp3} missing.")
        else:
            script = ScriptModel.model_validate(json.loads(args.script.read_text()))
            chapter = next(c for c in script.chapters if c.number == args.chapter)
            expected = " ".join(line.text for line in chapter.lines)
            print(f"\nWhisper round-trip ({args.whisper_model}):")
            ratio, divergences = whisper_roundtrip(mp3, expected, args.whisper_model)
            print(f"  similarity {ratio:.3f}")
            for d in divergences:
                print(d)
            if ratio < 0.92:
                n_failing += 1

    raise SystemExit(1 if n_failing else 0)


if __name__ == "__main__":
    main()
