# Reference voice sources

All clips in this directory are 5–15 s single-voice samples used as reference audio for Chatterbox (voice-cloning TTS). Every clip must be attributable to a public-domain or Creative-Commons source.

## Current clips

### `gatsby_ref.wav` — Gatsby (Tomas Peter, LibriVox Dramatic Reading)

- **Source**: *The Great Gatsby (Version 5, Dramatic Reading)*, LibriVox 2025
- **Reader (in role)**: Tomas Peter as Jay Gatsby
- **File**: `greatgatsby_05_fitzgerald.mp3`
- **URL**: https://archive.org/download/greatgatsby5_2510_librivox/greatgatsby_05_fitzgerald.mp3
- **LibriVox catalog page**: https://librivox.org/the-great-gatsby-version-5-by-f-scott-fitzgerald/
- **Timestamps**: 1083.8s–1091.7s (7.9 s)
- **Content**: Gatsby describing his house — "I keep it always full of interesting people, night and day. People who do interesting things. Celebrated people."
- **Why this clip**: Sustained single-voice Gatsby dialogue with the exact emotional register we need for our script's Gatsby-as-radiant-salesman lines.

### `daisy_ref.wav` — Daisy (Jasmin Salma, LibriVox Dramatic Reading)

- **Source**: same as above
- **Reader (in role)**: Jasmin Salma as Daisy Buchanan
- **File**: `greatgatsby_05_fitzgerald.mp3`
- **Timestamps**: 1343.5s–1352.8s (9.3 s)
- **Content**: Shirts-scene Daisy — "It makes me sad because I've never seen such beautiful shirts before."
- **Why this clip**: Daisy's emotional peak in Chapter 5 — pure single voice, no narrator overlap, crying-through-her-voice quality that Fitzgerald describes as her "voice full of money" signature.

## Legal status

*The Great Gatsby* (F. Scott Fitzgerald, 1925) entered the US public domain on 1 January 2021. LibriVox recordings are released into the public domain by their readers. Both conditions are satisfied: the underlying text and the recording performance are both PD. No attribution is legally required, but it is given here for auditability.

## Extraction commands

For reproducibility:

```bash
SRC=voice_samples/_librivox_src/greatgatsby_05.mp3
ffmpeg -y -ss 1083.8 -to 1091.7 -i "$SRC" -ac 1 -ar 24000 voice_samples/gatsby_ref.wav
ffmpeg -y -ss 1343.5 -to 1352.8 -i "$SRC" -ac 1 -ar 24000 voice_samples/daisy_ref.wav
```

## How timestamps were chosen

Rather than listening through the 29-minute chapter manually, the reunion-scene content was located via `faster-whisper` transcription with word-level timestamps. A short script (`/tmp/find_clips.py` during development) matched known dialogue lines from our `script.json` ("Five years next November", "It's stopped", etc.) against the Whisper output and returned their time ranges. Contextual passages were then inspected to find sustained single-voice moments. This kept sourcing auditable and reproducible — the same Whisper pass against a different LibriVox reading would surface equivalent timestamps.
