"""Kokoro TTS backend.

Kokoro is a StyleTTS2-style model (82M params) — non-autoregressive,
deterministic, runs fast on CPU. 28 English preset voices. Emotion
is implicit (driven by punctuation / phrasing), so `Emotion` fields
are used as phrasing hints only.

Reference: https://huggingface.co/hexgrad/Kokoro-82M
"""
from __future__ import annotations

import io
from typing import Optional

import numpy as np
import soundfile as sf

from .backend import Emotion, TTSBackend, Voice


# Curated English preset voices with tagged traits so the caster can reason
# about them. Tags are subjective — update as we listen and learn.
_VOICES: list[Voice] = [
    # American Female
    Voice("af_heart",    "Heart (AF)",    "female", "young",  "en-US", ["warm", "expressive", "default"]),
    Voice("af_bella",    "Bella (AF)",    "female", "young",  "en-US", ["bright", "youthful"]),
    Voice("af_nicole",   "Nicole (AF)",   "female", "adult",  "en-US", ["cool", "composed", "dry"]),
    Voice("af_nova",     "Nova (AF)",     "female", "adult",  "en-US", ["clear", "confident"]),
    Voice("af_sarah",    "Sarah (AF)",    "female", "adult",  "en-US", ["warm", "grounded"]),
    Voice("af_sky",      "Sky (AF)",      "female", "young",  "en-US", ["light", "airy"]),
    Voice("af_aoede",    "Aoede (AF)",    "female", "adult",  "en-US", ["musical", "refined"]),
    Voice("af_kore",     "Kore (AF)",     "female", "young",  "en-US", ["bright", "inquisitive"]),
    Voice("af_jessica",  "Jessica (AF)",  "female", "adult",  "en-US", ["friendly", "natural"]),
    Voice("af_river",    "River (AF)",    "female", "adult",  "en-US", ["calm", "steady"]),
    Voice("af_alloy",    "Alloy (AF)",    "female", "adult",  "en-US", ["professional"]),
    # American Male
    Voice("am_michael",  "Michael (AM)",  "male",   "adult",  "en-US", ["authoritative", "warm"]),
    Voice("am_fenrir",   "Fenrir (AM)",   "male",   "adult",  "en-US", ["deep", "serious"]),
    Voice("am_onyx",     "Onyx (AM)",     "male",   "adult",  "en-US", ["deep", "smooth"]),
    Voice("am_liam",     "Liam (AM)",     "male",   "young",  "en-US", ["friendly", "youthful"]),
    Voice("am_echo",     "Echo (AM)",     "male",   "adult",  "en-US", ["neutral", "clear"]),
    Voice("am_eric",     "Eric (AM)",     "male",   "adult",  "en-US", ["grounded"]),
    Voice("am_adam",     "Adam (AM)",     "male",   "adult",  "en-US", ["everyman"]),
    Voice("am_puck",     "Puck (AM)",     "male",   "young",  "en-US", ["mischievous", "quick"]),
    Voice("am_santa",    "Santa (AM)",    "male",   "old",    "en-US", ["jolly", "mature"]),
    # British Female
    Voice("bf_emma",     "Emma (BF)",     "female", "adult",  "en-GB", ["refined", "warm"]),
    Voice("bf_isabella", "Isabella (BF)", "female", "adult",  "en-GB", ["refined", "poised"]),
    Voice("bf_alice",    "Alice (BF)",    "female", "adult",  "en-GB", ["crisp", "articulate"]),
    Voice("bf_lily",     "Lily (BF)",     "female", "young",  "en-GB", ["bright", "clear"]),
    # British Male
    Voice("bm_george",   "George (BM)",   "male",   "mature", "en-GB", ["authoritative", "literary", "narrator"]),
    Voice("bm_fable",    "Fable (BM)",    "male",   "adult",  "en-GB", ["measured", "narrator"]),
    Voice("bm_lewis",    "Lewis (BM)",    "male",   "adult",  "en-GB", ["deep", "thoughtful"]),
    Voice("bm_daniel",   "Daniel (BM)",   "male",   "adult",  "en-GB", ["clear", "classic"]),
]


def _pronounce(text: str) -> str:
    """Normalize text for natural speech without mutating the script.

    Kept here (backend-local) rather than in script.json because it's a
    rendering concern — the faithful-wording contract preserves source text.
    """
    import re as _re
    # Slashes in name pairs and common slash-as-conjunction usages should read
    # as "and". ("Lydia/Wickham" → "Lydia and Wickham")
    text = _re.sub(r"(?<=\w)/(?=\w)", " and ", text)
    # Common standalone symbols that Kokoro would spell out.
    text = text.replace("&", " and ")
    # Collapse any double spaces we introduced.
    text = _re.sub(r"\s+", " ", text)
    return text


class KokoroBackend(TTSBackend):
    name = "kokoro"

    def __init__(self, lang_code: str = "a", default_speed: float = 1.0):
        # Lazy import so importing this module doesn't load 500MB of torch.
        from kokoro import KPipeline
        self._pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        self._default_speed = default_speed
        self._sample_rate = 24000

    def list_voices(self) -> list[Voice]:
        return list(_VOICES)

    def supports_emotion(self) -> bool:
        # Kokoro is non-autoregressive and does not accept an emotion input.
        # Returning False tells the pipeline "don't expect emotion in output".
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

        # Map Emotion.pace → speed multiplier (Kokoro's only "emotion" lever).
        # pace is in [-1, +1]. Widened coefficient 0.28 → 0.40 after the
        # Gatsby scene showed Kokoro's American voices with less natural pitch
        # range than British — structural prosody (pace + pauses) has to do
        # more work. pace: -0.3 is now ~0.88× speed (was 0.92×).
        effective_speed = speed * self._default_speed
        if emotion is not None:
            effective_speed *= 1.0 + 0.40 * emotion.pace
            # High-intensity lines decelerate harder; peak lines (0.85+)
            # double the coefficient so they actually *land* instead of
            # reading past themselves.
            if emotion.intensity >= 0.85:
                effective_speed *= 1.0 - 0.09 * (emotion.intensity - 0.5)
            elif emotion.intensity >= 0.75:
                effective_speed *= 1.0 - 0.05 * (emotion.intensity - 0.5)

        # Drama punctuation: for intensity ≥ 0.90 lines that end in a period,
        # append an ellipsis to what Kokoro sees. Kokoro tapers the final word
        # into the ellipsis instead of clipping it, giving peak lines a
        # naturally-held final syllable. Script text stays byte-faithful —
        # this only affects what the synthesizer receives.
        text_for_synth = text
        if emotion is not None and emotion.intensity >= 0.90 and text.rstrip().endswith((".", "!", "?")):
            text_for_synth = text.rstrip() + "…"

        # Kokoro returns a generator of (graphemes, phonemes, audio) tuples,
        # one per sentence-ish chunk. Concatenate them into one clip.
        chunks: list[np.ndarray] = []
        for _gs, _ps, audio in self._pipeline(text_for_synth, voice=voice_id, speed=effective_speed):
            if hasattr(audio, "cpu"):
                audio = audio.cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))

        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for text: {text[:60]!r}")

        full = np.concatenate(chunks)
        buf = io.BytesIO()
        sf.write(buf, full, self._sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue(), self._sample_rate
