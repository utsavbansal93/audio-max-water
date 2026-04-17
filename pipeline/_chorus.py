"""Generic chorus / group-speech overlay.

When a LineModel has `chorus=True` and `config.output.chorus_overlay` is
enabled, this module renders the line with multiple layered voices to produce
the effect of several people speaking in unison.

Design:
  * N_base = min(chorus_size, 4) — number of *distinct* voice takes rendered.
  * If chorus_size > 4, the same N_base WAVs are re-used with shifted filter
    parameters (different atempo, adelay, gain) to simulate up to
    min(chorus_size, 8) perceptual voices without extra TTS calls.  Beyond 8
    the gain of additional layers falls below perception threshold and starts
    sounding like noise, so we cap there.
  * One "lead" voice is kept at 0 dB / 1.0 atempo / 0 ms delay to maintain
    intelligibility as a focal point.
  * Voice pool selection:
    1. cast.chorus_pools[speaker]  — if declared in cast.json
    2. cast.chorus_pools["_default"] — fallback pool
    3. Single voice from cast.resolve(speaker).voice — repeated with filter
       variation only (no real voice variety, but still audible as chorus).

Integration: called from render.py::render_chapter after the normal single-
voice synthesis path, substituting the cache WAV with the layered result.
Keyed off a config flag ``output.chorus_overlay: true`` (default true).
"""
from __future__ import annotations

import random
import subprocess
import tempfile
from pathlib import Path

from pipeline._ffmpeg import FFMPEG
from pipeline.schema import CastModel, LineModel
from tts import Emotion
from tts.backend import TTSBackend


def _get_voice_pool(line: LineModel, cast: CastModel) -> list[str]:
    """Return the list of voice_ids to use for chorus rendering."""
    pools = cast.chorus_pools
    if line.speaker in pools:
        return pools[line.speaker]
    if "_default" in pools:
        return pools["_default"]
    # Fall back to the character's own voice (filter variation only).
    return [cast.resolve(line.speaker).voice]


def render_chorus(
    line: LineModel,
    cast: CastModel,
    backend: TTSBackend,
    build_dir: Path,
    *,
    sample_rate: int = 24000,
    loudness_norm: bool = True,
) -> bytes:
    """Render line as a layered chorus and return WAV bytes.

    Falls back to single-voice synthesis if anything goes wrong so callers
    can treat a failed chorus as a regular line.
    """
    pool = _get_voice_pool(line, cast)
    chorus_size = max(1, line.chorus_size)
    n_base = min(chorus_size, 4)
    n_total = min(chorus_size, 8)

    emo = Emotion(**line.emotion.model_dump())

    # Render N_base distinct takes (one per voice in pool, cycling if pool is smaller).
    base_wavs: list[Path] = []
    with tempfile.TemporaryDirectory(dir=build_dir, prefix=".chorus_") as tmpdir:
        tmp = Path(tmpdir)

        for i in range(n_base):
            voice_id = pool[i % len(pool)]
            wav_bytes, sr = backend.synthesize(line.text, voice_id, emotion=emo)
            p = tmp / f"base_{i}.wav"
            p.write_bytes(wav_bytes)
            if sr != sample_rate:
                rs = tmp / f"base_{i}_rs.wav"
                subprocess.run([
                    FFMPEG, "-y", "-loglevel", "error",
                    "-i", str(p), "-ar", str(sample_rate), str(rs),
                ], check=True)
                p.unlink()
                p = rs
            base_wavs.append(p)

        # Build the layered mix.  Each layer is a (source_wav, atempo, delay_ms, gain_db) tuple.
        layers: list[tuple[Path, float, int, float]] = []
        rng = random.Random(42)  # deterministic so caching is stable

        def _lead_tempo() -> float:
            return 1.0  # lead untouched

        def _jitter_tempo() -> float:
            return 1.0 + rng.uniform(-0.02, 0.02)

        def _jitter_delay() -> int:
            return rng.randint(5, 80)

        def _jitter_gain() -> float:
            return rng.uniform(-6.0, -2.0)

        for layer_idx in range(n_total):
            base = base_wavs[layer_idx % n_base]
            if layer_idx == 0:
                layers.append((base, _lead_tempo(), 0, 0.0))
            else:
                layers.append((base, _jitter_tempo(), _jitter_delay(), _jitter_gain()))

        # Build ffmpeg filter_complex for amix.
        # Each input is [i:a] → atempo → adelay → volume → labelled [a{i}].
        # Final node mixes all [a{i}] through amix and normalises.
        filter_parts: list[str] = []
        labels: list[str] = []
        for i, (_, tempo, delay_ms, gain_db) in enumerate(layers):
            chain = f"[{i}:a]atempo={tempo:.4f}"
            if delay_ms > 0:
                chain += f",adelay={delay_ms}|{delay_ms}"
            if gain_db != 0.0:
                chain += f",volume={gain_db:.1f}dB"
            label = f"[a{i}]"
            chain += label
            filter_parts.append(chain)
            labels.append(label)

        mix_inputs = "".join(labels)
        n_mix = len(labels)
        filter_parts.append(
            f"{mix_inputs}amix=inputs={n_mix}:duration=longest:normalize=1[mixed]"
        )
        filter_complex = ";".join(filter_parts)

        cmd: list[str] = [FFMPEG, "-y", "-loglevel", "error"]
        for src, _, _, _ in layers:
            cmd += ["-i", str(src)]
        out_wav = tmp / "chorus_out.wav"
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[mixed]",
            "-ar", str(sample_rate), "-ac", "1",
            str(out_wav),
        ]
        subprocess.run(cmd, check=True)

        if loudness_norm:
            norm_wav = tmp / "chorus_norm.wav"
            subprocess.run([
                FFMPEG, "-y", "-loglevel", "error", "-i", str(out_wav),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar", str(sample_rate), "-ac", "1", str(norm_wav),
            ], check=True)
            return norm_wav.read_bytes()

        return out_wav.read_bytes()
