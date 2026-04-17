"""Shared dialogue-attribution-tag detection.

Both `pipeline.normalize` (post-parse splitter) and `pipeline.render` (pause-gap
chooser) need to recognize the same set of "this narrator line is a dialogue
attribution tag" patterns. Living apart, they drift — the splitter thinks
"Rig said." is a tag and splits it, but the pause-decider thinks it's regular
narration and uses a long gap. This module is the single source of truth.

Three signals count a narrator line as an attribution tag:

1. Short length (≤30 chars) when sandwiched between same-speaker dialogue — the
   "he said" fallback without strict pattern match. Catches almost any
   short mid-dialogue narrator interjection.

2. A `_TAG_STARTS` prefix (`he said`, `she replied`, `her companion`, ...)
   with ≤80 chars total. Allows action-beat tags like
   "she said, pulling on Rig's hand."

3. A `<SpeakerName> <tag_verb>` prefix, where the name matches the adjacent
   dialogue's speaker. Used when the parser emits "Rig said" explicitly
   rather than "he said". ≤80 chars total; allows action beats.

Plus, for the normalizer specifically, we also need a regex that matches the
LUMPED patterns (the text LIVING on a character speaker's line, not a narrator
line) so we can split them. That's `SANDWICHED_TAG_RE` and `TRAILING_TAG_RE`.
"""
from __future__ import annotations

import functools
import re


# Third-person pronouns + classic "he said" style tag verbs.
# Ordered by frequency in the renders we've shipped so far.
_TAG_STARTS = (
    "he said", "she said", "he replied", "she replied", "he added", "she added",
    "he asked", "she asked", "he whispered", "she whispered", "he answered",
    "she answered", "he muttered", "she muttered", "he continued", "she continued",
    "they said", "they asked", "they replied",
    "her companion", "his companion",
)

# Attribution verbs we recognize for speaker-name-based tags.
# Not exhaustive — "bellowed", "hissed" etc. exist but are rare; expand on demand.
_TAG_VERBS = (
    "said", "asked", "replied", "answered", "insisted", "agreed", "cried",
    "muttered", "whispered", "shouted", "called", "rejoined", "snapped",
    "demanded", "explained", "began", "added", "continued", "repeated",
    "told", "inquired", "urged", "nodded", "grinned", "groaned",
)

# Lazy-compile the alternations.
_VERBS_ALT = r"(?:" + "|".join(_TAG_VERBS) + r")"
_PRONOUN_ALT = r"(?:he|she|they)"

# --- Predicate used by render.py for pause-gap decisions --------------------

def text_looks_like_attribution_tag(text: str, speaker_hint: str | None = None) -> bool:
    """Does this narrator text read like a dialogue attribution tag?

    `speaker_hint` is the speaker name of the PREVIOUS (or NEXT) dialogue line;
    when supplied, enables the `<Name> <verb>` pattern check. When None, only
    the pronoun and length-based heuristics apply.
    """
    text_norm = text.strip().lower().rstrip(",.;:")
    if len(text) <= 30:
        return True
    if len(text) <= 80 and any(text_norm.startswith(t) for t in _TAG_STARTS):
        return True
    if speaker_hint and len(text) <= 80:
        name = speaker_hint.lower()
        if re.match(rf"^{re.escape(name)}\s+{_VERBS_ALT}\b", text_norm):
            return True
    return False


# --- Regexes used by normalize.py for splitting LUMPED lines ---------------
#
# These match a character-speaker's text when it contains an embedded
# attribution tag that should be on its own narrator line.
#
# `SANDWICHED_TAG_RE` matches: `"A," <tag> "B"` where tag is either
# `<pronoun> <verb>` or `<Name> <verb>`, optionally with an action beat.
# `TRAILING_TAG_RE` matches: `"A," <tag>.` at end of line.
#
# Both use non-greedy to stop at the first quote boundary.

def _compile_sandwich(name_pattern: str) -> re.Pattern:
    return re.compile(
        rf'^(?P<d1>.+?[.!?,"])\s+(?P<tag>{name_pattern}\s+{_VERBS_ALT}\b[^"]*?[,.])\s+(?P<d2>"[^"]*"?.*)$',
        re.DOTALL | re.IGNORECASE,
    )


def _compile_trailing(name_pattern: str) -> re.Pattern:
    return re.compile(
        rf'^(?P<d1>.+?[.!?,"])\s+(?P<tag>{name_pattern}\s+{_VERBS_ALT}\b[^"]*)\.?\s*$',
        re.DOTALL | re.IGNORECASE,
    )


# For pronoun-based lumped tags (he/she/they).
SANDWICHED_PRONOUN_TAG_RE = _compile_sandwich(_PRONOUN_ALT)
TRAILING_PRONOUN_TAG_RE = _compile_trailing(_PRONOUN_ALT)


@functools.lru_cache(maxsize=256)
def make_name_tag_regexes(speaker: str) -> tuple[re.Pattern, re.Pattern]:
    """Compile a (sandwich, trailing) regex pair for a specific speaker name,
    allowing honorifics with dots (e.g. "Dr. Nash")."""
    name = rf"{re.escape(speaker)}"
    # Allow the literal speaker name; for honorifics the name already contains
    # the dot, so re.escape handles it.
    return (_compile_sandwich(name), _compile_trailing(name))
