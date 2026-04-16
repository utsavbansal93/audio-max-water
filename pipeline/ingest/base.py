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
    """Pre-parsed story awaiting LLM structuring.

    `metadata` is a free-form grab bag for per-format extras that
    don't fit the core schema — e.g. `cover_bytes` + `cover_ext` for
    EPUB covers, `language` for sources where it's reliably known.
    """
    title: str
    author: str = "unknown"
    language: str = "en"
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


# --- author extraction from text -------------------------------------------

# Matches "by Name", "written by Name", "a novel by Name", "author: Name",
# with optional italic markers (* or _) wrapping the byline. Case-insensitive.
_BYLINE_RE = re.compile(
    r"^\s*[\*_]*\s*"
    r"(?:by|written\s+by|a\s+(?:novel|book|story|memoir|work)\s+by|author\s*:?)\s+"
    r"\*?_?([^\n*_]+?)_?\*?\s*$",
    re.IGNORECASE,
)

# Document metadata "Author" fields that are almost never real authors — these
# are the tools that produced the file announcing themselves. If the
# metadata author matches one of these, we ignore it.
_META_AUTHOR_BAN_LIST = {
    "",
    "unknown",
    "administrator",
    "user",
    "admin",
    "calibre",
    "calibre-ebook.com",
    "adobe acrobat",
    "adobe",
    "microsoft office user",
    "microsoft word",
    "microsoft",
    "word",
    "pages",
    "libreoffice",
    "openoffice",
    "google docs",
    "zipper",
    "pdftex",
    "latex",
    "kindle",
    "amazon",
    "smashwords",
    "epub",
}


def extract_author_from_text(
    text: str,
    *,
    max_chars: int = 800,
    max_lines: int = 25,
) -> str | None:
    """Scan the opening text for a `by <Name>` byline.

    For PDF and DOCX sources, the document-metadata Author field is
    frequently garbage (zipper apps, converters, Office defaults). The
    text itself is more reliable — a real book prints the author's name
    on its title page, usually on a short standalone line right after
    the title.

    Strategy:
      - Look at the first `max_chars` characters / `max_lines` lines.
      - Skip blank lines.
      - Skip long lines (> 100 chars) — they're prose, not bylines.
      - Match "by X", "written by X", "a novel by X", "author: X",
        with optional italic markers. Case-insensitive.
      - Reject captures that are too short, too long, or look like prose
        ending (trailing "and", "or", "to"…).

    Returns the cleaned author string, or None if no confident match.
    """
    head = text[:max_chars]
    for i, line in enumerate(head.splitlines()):
        if i >= max_lines:
            break
        stripped = line.strip()
        if not stripped or len(stripped) > 100:
            continue
        m = _BYLINE_RE.match(stripped)
        if not m:
            continue
        author = m.group(1).strip().rstrip(",.;:").strip("*_").strip()
        # Length guardrails.
        if not (2 <= len(author) <= 80):
            continue
        # Reject captures that end in a connector word — usually means the
        # match absorbed too much context.
        last_word = author.split()[-1].lower() if author.split() else ""
        if last_word in {"and", "or", "to", "the", "of", "in", "for", "with"}:
            continue
        return author
    return None


def clean_metadata_author(meta_author: str | None) -> str | None:
    """Return `meta_author` iff it looks like a plausible human author,
    else None. Used as a fallback when text-based extraction fails."""
    if not meta_author:
        return None
    cleaned = meta_author.strip()
    if not cleaned or len(cleaned) > 80:
        return None
    # Case-insensitive ban-list match (substring OK — "Microsoft Office User"
    # has "microsoft" inside).
    low = cleaned.lower()
    for banned in _META_AUTHOR_BAN_LIST:
        if banned and banned in low:
            return None
    return cleaned
