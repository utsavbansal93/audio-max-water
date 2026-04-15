"""MLX-Kokoro TTS backend — same Kokoro-82M weights, MLX inference path.

Uses https://github.com/Blaizzy/mlx-audio with the mlx-community/Kokoro-82M-bf16
weights. Runs natively on Apple Silicon Metal / Neural Engine — typically
2-3× faster than the torch path on M-series hardware and lighter on battery.

Voice list and emotion-mapping logic mirrors KokoroBackend exactly, since
the weights are identical — only the inference runtime changes.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from .backend import Emotion, TTSBackend, Voice
from .kokoro_backend import _VOICES, _pronounce


# MLX-Kokoro uses single-letter language codes matching the Kokoro package.
_ACCENT_TO_LANG = {"en-US": "a", "en-GB": "b"}


class MLXKokoroBackend(TTSBackend):
    name = "mlx-kokoro"

    def __init__(
        self,
        model: str = "mlx-community/Kokoro-82M-bf16",
        default_speed: float = 1.0,
        sample_rate: int = 24000,
    ):
        self._default_speed = default_speed
        self._sample_rate = sample_rate
        # Load the model ONCE here and pass the instance to every synth call.
        # If we passed the repo-id string each time, mlx-audio's generate_audio
        # would re-run load_model per line (measured ~2× slowdown vs torch).
        from mlx_audio.tts.generate import generate_audio
        from mlx_audio.tts.utils import load_model
        self._gen = generate_audio
        self._model = load_model(model_path=model)
        self._voices_by_id: dict[str, Voice] = {v.id: v for v in _VOICES}

    def list_voices(self) -> list[Voice]:
        return list(_VOICES)

    def supports_emotion(self) -> bool:
        # Same Kokoro weights — still no explicit emotion input.
        return False

    def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: Optional[Emotion] = None,
        speed: float = 1.0,
    ) -> tuple[bytes, int]:
        if not text.strip():
            raise ValueError("synthesize() called with empty text")
        text = _pronounce(text)

        # Same emotion → speed mapping as the torch backend so A/B renders
        # are apples-to-apples.
        effective_speed = speed * self._default_speed
        if emotion is not None:
            effective_speed *= 1.0 + 0.28 * emotion.pace
            if emotion.intensity >= 0.75:
                effective_speed *= 1.0 - 0.04 * (emotion.intensity - 0.5)

        voice = self._voices_by_id.get(voice_id)
        lang = _ACCENT_TO_LANG.get(voice.accent, "a") if voice else "a"

        with tempfile.TemporaryDirectory(prefix="mlx_tts_") as td:
            self._gen(
                text=text,
                model=self._model,
                voice=voice_id,
                speed=effective_speed,
                lang_code=lang,
                output_path=td,
                file_prefix="line",
                audio_format="wav",
                save=True,
                verbose=False,
                play=False,
                join_audio=True,
            )
            # mlx-audio writes `line.wav` with join_audio=True; fall back to
            # any wav if that name isn't present.
            candidates = sorted(Path(td).glob("*.wav"))
            if not candidates:
                raise RuntimeError("mlx-audio produced no WAV output")
            wav_path = next((p for p in candidates if p.name == "line.wav"), candidates[0])
            wav_bytes = wav_path.read_bytes()
        return wav_bytes, self._sample_rate
