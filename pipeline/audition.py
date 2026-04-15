"""Render audition samples for a character across multiple candidate voices.

Writes samples/<dest>/<character>/<voice_id>_<slug>.wav so you can A/B by
ear without listening to a whole chapter.

Usage:
    python -m pipeline.audition --character Gatsby \
        --voices am_onyx am_fenrir am_eric am_echo bm_lewis \
        --lines "Five years next November." \
                "Absolutely. I keep it full of interesting people, night and day." \
        --emotion-pace -0.15 --emotion-intensity 0.8
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from tts import Emotion, get_backend


REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO / "config.yaml").read_text())


def _slug(text: str, n: int = 28) -> str:
    s = re.sub(r"[^\w\s-]", "", text).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:n].rstrip("_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--character", required=True)
    ap.add_argument("--voices", nargs="+", required=True, help="Voice ids to audition")
    ap.add_argument("--lines", nargs="+", required=True, help="Lines to render per voice")
    ap.add_argument("--dest", default="samples/audition", type=Path)
    ap.add_argument("--backend", default=CFG["backend"])
    ap.add_argument("--emotion-pace", type=float, default=-0.1)
    ap.add_argument("--emotion-intensity", type=float, default=0.75)
    ap.add_argument("--emotion-label", default="vulnerable")
    args = ap.parse_args()

    backend = get_backend(args.backend)
    emo = Emotion(label=args.emotion_label, intensity=args.emotion_intensity, pace=args.emotion_pace)

    out_dir = args.dest / args.character
    out_dir.mkdir(parents=True, exist_ok=True)
    for voice_id in args.voices:
        for line in args.lines:
            fname = f"{voice_id}__{_slug(line)}.wav"
            path = out_dir / fname
            wav_bytes, _sr = backend.synthesize(line, voice_id, emotion=emo)
            path.write_bytes(wav_bytes)
            print(f"  {path}")


if __name__ == "__main__":
    main()
