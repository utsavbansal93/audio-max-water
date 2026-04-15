"""Chatterbox TTS backend (Resemble AI, autoregressive LLM-based TTS).

Why it's here: Kokoro is non-autoregressive and has no emotion input. The
Emotion.intensity field in our schema had nowhere to go in Kokoro.
Chatterbox exposes an explicit `exaggeration` parameter that we map
intensity to — finally giving emotion a real knob.

Voice identity: Chatterbox does not have a preset voice library. Instead,
it clones from a 5–15 s reference WAV. We store reference clips in
`voice_samples/<voice_id>.wav`; `voice_id` is the filename stem.

Speed: Chatterbox has no native speed parameter. We post-process with
ffmpeg's `atempo` filter for pace > 0 or < 0 requests (atempo accepts
0.5–2.0 in one pass).

Model loaded once in __init__ per the pattern from DECISIONS #0009 —
per-call reload would cost ~3 s each.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch

from .backend import Emotion, TTSBackend, Voice


_REPO = Path(__file__).resolve().parents[1]
VOICE_SAMPLES_DIR = _REPO / "voice_samples"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def install_clean_exit_hook() -> None:
    """Bypass a sentencepiece shutdown-time crash on macOS.

    When Chatterbox is loaded, the Python interpreter crashes with SIGBUS
    inside `_sentencepiece.cpython-312-darwin.so` during normal shutdown —
    the work already completed, but the native-module destructor trips a
    KERN_PROTECTION_FAILURE and macOS shows a 'Python quit unexpectedly'
    dialog. Registering `os._exit(0)` as the last atexit hook makes the
    interpreter hard-exit before module destructors run, skipping the bad
    cleanup path.

    Called from ChatterboxBackend.__init__; harmless for processes that
    never load Chatterbox.
    """
    import atexit, os, sys
    def _hard_exit():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(0)
    atexit.register(_hard_exit)


def _map_intensity_to_exaggeration(intensity: float) -> float:
    """Map Emotion.intensity [0,1] to Chatterbox exaggeration.

    Default exaggeration is 0.5; 0 = flat, 1 = theatrical.
    Our default Emotion.intensity is 0.4 (neutral narration).
    Linear mapping from [0.3, 0.95] — leaves headroom at both ends.
    """
    return max(0.30, min(0.95, 0.30 + 0.65 * intensity))


def _atempo_chain(ratio: float) -> list[str]:
    """Build ffmpeg `atempo=...` chain. atempo accepts 0.5..2.0 per stage;
    chain multiple stages for extreme ratios (we never need this for our
    pace range, but it's correct)."""
    if abs(ratio - 1.0) < 0.01:
        return []
    stages = []
    r = ratio
    while r < 0.5:
        stages.append(0.5)
        r /= 0.5
    while r > 2.0:
        stages.append(2.0)
        r /= 2.0
    stages.append(r)
    return [f"atempo={s:.4f}" for s in stages]


def _resample_and_stretch(
    wav: np.ndarray,
    src_sr: int,
    dst_sr: int,
    atempo_ratio: float,
) -> bytes:
    """Run wav through ffmpeg for sample-rate + pace adjustment, return WAV bytes."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fin, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fout:
        sf.write(fin.name, wav, src_sr, subtype="PCM_16")
        fin.close(); fout.close()

        cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", fin.name]
        filters = _atempo_chain(atempo_ratio)
        if filters:
            cmd += ["-filter:a", ",".join(filters)]
        cmd += ["-ar", str(dst_sr), "-ac", "1", fout.name]
        subprocess.run(cmd, check=True)
        data = Path(fout.name).read_bytes()
        Path(fin.name).unlink(missing_ok=True)
        Path(fout.name).unlink(missing_ok=True)
        return data


class ChatterboxBackend(TTSBackend):
    name = "chatterbox"

    def __init__(self, device: str = "mps", cfg_weight: float = 0.5, temperature: float = 0.8):
        # Install the shutdown-crash workaround *before* loading the model —
        # once the native modules are mapped in, any crash-on-exit trips the
        # OS dialog we're trying to avoid.
        install_clean_exit_hook()
        from chatterbox.tts import ChatterboxTTS
        self._model = ChatterboxTTS.from_pretrained(device=device)
        self._cfg_weight = cfg_weight
        self._temperature = temperature
        self._sr = getattr(self._model, "sr", 24000)

    def list_voices(self) -> list[Voice]:
        """Every WAV in voice_samples/ is a Voice. voice_id = filename stem."""
        voices: list[Voice] = []
        if not VOICE_SAMPLES_DIR.exists():
            return voices
        for p in sorted(VOICE_SAMPLES_DIR.glob("*.wav")):
            voices.append(Voice(
                id=p.stem,
                display_name=p.stem.replace("_", " ").title(),
                gender="neutral",
                age="adult",
                accent="unknown",
                tags=["reference-clip"],
            ))
        return voices

    def supports_emotion(self) -> bool:
        return True

    def requires_reference_audio(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: Optional[Emotion] = None,
        speed: float = 1.0,
    ) -> tuple[bytes, int]:
        if not text.strip():
            raise ValueError("synthesize() called with empty text")

        ref_path = VOICE_SAMPLES_DIR / f"{voice_id}.wav"
        if not ref_path.exists():
            raise FileNotFoundError(
                f"Chatterbox reference clip not found: {ref_path}. "
                f"Add a 5–15 s WAV for the voice, or use a Kokoro voice via cast.json."
            )

        exaggeration = _map_intensity_to_exaggeration(emotion.intensity if emotion else 0.5)

        # Pace → post-process speed ratio. emotion.pace is in [-1, +1].
        # Map: pace = 0 → 1.0x; pace = -0.3 → 0.88x; pace = +0.3 → 1.12x.
        # Same coefficient family as the Kokoro backend so the Emotion.pace
        # field behaves comparably across engines.
        pace = (emotion.pace if emotion else 0.0)
        atempo_ratio = 1.0 + 0.40 * pace

        with torch.inference_mode():
            tensor = self._model.generate(
                text,
                audio_prompt_path=str(ref_path),
                exaggeration=exaggeration,
                cfg_weight=self._cfg_weight,
                temperature=self._temperature,
            )
        wav_np = tensor.cpu().numpy()
        if wav_np.ndim > 1:
            wav_np = wav_np.squeeze()
        wav_np = wav_np.astype(np.float32)

        if abs(atempo_ratio - 1.0) < 0.01:
            buf = io.BytesIO()
            sf.write(buf, wav_np, self._sr, format="WAV", subtype="PCM_16")
            return buf.getvalue(), self._sr

        stretched = _resample_and_stretch(wav_np, self._sr, self._sr, atempo_ratio)
        return stretched, self._sr
