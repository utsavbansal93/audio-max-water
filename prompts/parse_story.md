# Parse a story into a structured script

You receive a prose story and produce STRICT JSON matching this schema:

```json
{
  "title": "string",
  "book_context": "string — 2–5 sentences grounding any emotion labels in the broader work (character arcs, prior events). If the story is self-contained, 'none' is fine.",
  "characters": [
    {
      "name": "Canonical name used as 'speaker' value",
      "age_hint": "e.g. '20s', 'teen', 'middle-aged', 'elderly'",
      "gender": "male | female | neutral",
      "accent": "e.g. 'en-US', 'en-GB', or 'unspecified'",
      "personality": "3–8 words capturing traits the actor should embody",
      "sample_lines": ["up to 3 short quotes from this character, used for voice auditions"]
    }
  ],
  "chapters": [
    {
      "number": 1,
      "title": "string",
      "lines": [
        {
          "speaker": "narrator | <character name>",
          "text": "BYTE-VERBATIM text from the source. Do NOT paraphrase.",
          "emotion": {
            "label": "neutral | calm | tender | warm | joy | excited | wry | dry | melancholic | sad | anxious | embarrassed | humbled | angry | firm | commanding | whisper | urgent | resolute | vulnerable | hopeful | awkward | formal",
            "intensity": 0.0,
            "pace": 0.0,
            "notes": "optional: 1-sentence direction for the actor, grounded in book_context"
          }
        }
      ]
    }
  ]
}
```

## Hard rules

1. **Faithful wording.** `text` is a byte-verbatim extract from the source. Do not paraphrase, summarize, add, or re-order words. A downstream validator concatenates all `text` values and diffs against the source — any divergence aborts the pipeline.

2. **Speaker attribution.** Everything outside of quoted dialogue is `speaker: "narrator"`. Dialogue tags ("he said", "Elizabeth replied") stay with the narrator line they're attached to, UNLESS the whole line is the dialogue. Default: attach the tag to the dialogue line itself as narrator context — prefer splitting lines cleanly so voice handoffs sound natural.

3. **Character deduplication.** "Mom", "Mother", "Sarah's mom" collapse into one canonical name (use the fullest unambiguous form).

4. **Emotion grounding.** Emotion labels MUST reflect both local cues (dialogue tags, punctuation) AND the broader `book_context`. Example: Darcy saying "If your feelings are still what they were last April, tell me so at once" — locally this reads anxious; in context (after Hunsford rejection, after Lydia's elopement, after the unrequited letter) it is **vulnerable+resolute**, intensity ~0.8, pace slow. The `notes` field is where you give the actor subtext.

5. **Pace field.** -1.0 = slow, deliberate; 0.0 = default; +1.0 = rapid. Narration usually 0. Dialogue varies by emotion.

6. **Intensity field.** 0.0 = flat; 1.0 = theatrical. Most prose narration is 0.2–0.4; climactic dialogue is 0.6–0.9. Reserve 1.0 for genuine shouting / breaking down.

## Output

Only the JSON. No prose around it. No code fences. Parseable by `json.loads`.
