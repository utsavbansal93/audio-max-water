"""Ingestor ABC + RawStory / RawChapter dataclasses.

A RawStory is the unit that crosses the ingest → parse boundary. It is
the format-agnostic intermediate:
  - text is Unicode, whitespace-normalized, with scene breaks as `---`
  - chapters are separated structurally (headings, file sections, etc.)
  - no LLM has touched it yet

Parse then hands this to the LLM, which returns `script.json` in the
canonical `ScriptModel` shape.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


SCENE_BREAK = "---"


@dataclass
class RawChapter:
    number: int
    title: str
    text: str  # chapter body, whitespace-normalized; scene breaks = "---"


@dataclass
class RawStory:
    """Pre-parsed story awaiting LLM structuring."""
    title: str
    author: str = "unknown"
    source_format: str = ""
    chapters: list[RawChapter] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_source_md(self) -> str:
        """Render a canonical markdown representation used for:
          (a) LLM input (what the parse prompt sees)
          (b) validator reference (diff target for faithful-wording)

        Shape (single chapter — matches existing `stories/*.md`):
            # <title>
            <text>

        Shape (multiple chapters):
            # <title>
            *by <author>*                     (if author != "unknown")

            ## Chapter 1: <title>
            <text>
            ## Chapter 2: <title>
            <text>

        Rationale: for single-chapter stories, a `##` header would
        duplicate the `#` title and pollute the faithful-wording diff.
        `pipeline/validate.py::_normalize` strips `##` lines entirely
        (they're structural JSON, not spoken content) but keeps the
        `#` title text (which IS spoken as the narrator's opening line
        in the existing stories convention).
        """
        parts: list[str] = [f"# {self.title}", ""]
        if self.author and self.author.strip() and self.author != "unknown":
            parts.append(f"*by {self.author}*")
            parts.append("")
        if len(self.chapters) == 1:
            parts.append(self.chapters[0].text.strip())
            parts.append("")
        else:
            for ch in self.chapters:
                parts.append(f"## Chapter {ch.number}: {ch.title}")
                parts.append("")
                parts.append(ch.text.strip())
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    @property
    def total_words(self) -> int:
        return sum(len(re.findall(r"\w+", ch.text)) for ch in self.chapters)


class Ingestor(ABC):
    """Abstract file-format ingestor."""

    name: str = "abstract"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def ingest(self, path: Path) -> RawStory:
        """Read `path` and return a RawStory with at least one chapter."""


# --- shared helpers --------------------------------------------------------

_SCENE_BREAK_RE = re.compile(
    r"(?m)^\s*(?:\*\s*\*\s*\*|#\s*#\s*#|-\s*-\s*-|•\s*•\s*•|~\s*~\s*~)\s*$"
)


def normalize_scene_breaks(text: str) -> str:
    """Collapse common scene-break glyphs into the canonical `---` marker."""
    return _SCENE_BREAK_RE.sub(SCENE_BREAK, text)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of blank lines to exactly one blank line; strip
    trailing whitespace on each line. Keeps paragraph structure intact."""
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse 3+ blank lines to 2 (one blank between paragraphs).
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    return "\n".join(out).strip() + "\n"


def normalize_quotes(text: str) -> str:
    """Convert common Unicode smart quotes / dashes to ASCII equivalents
    so TTS backends pronounce punctuation predictably. Kept conservative:
    curly quotes → straight, em-dash → '--' (pause), en-dash → '-'."""
    replacements = {
        "\u201c": '"', "\u201d": '"',  # curly double
        "\u2018": "'", "\u2019": "'",  # curly single
        "\u2014": "--",                 # em-dash
        "\u2013": "-",                  # en-dash
        "\u2026": "...",                # horizontal ellipsis
        "\u00a0": " ",                  # nbsp
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def clean_text(text: str) -> str:
    """Apply all standard normalizations in order."""
    text = normalize_quotes(text)
    text = normalize_scene_breaks(text)
    text = normalize_whitespace(text)
    return text


def guess_title_from_path(path: Path) -> str:
    """Fallback title derived from filename: kebab/snake → Title Case."""
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(w.capitalize() for w in stem.split())
