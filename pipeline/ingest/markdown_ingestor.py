"""Markdown ingestor.

Uses H1 (`#`) and H2 (`##`) headings as chapter boundaries. The file's
top-level heading (if exactly one H1) becomes the story title; multiple
H1s are treated as chapters.

Single-heading files (like the existing `stories/*.md`) produce one
chapter — matching today's behavior so existing renders don't regress.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import (
    Ingestor,
    RawChapter,
    RawStory,
    clean_text,
    guess_title_from_path,
)


_H1_RE = re.compile(r"(?m)^\s*#\s+(.+?)\s*$")
_H2_RE = re.compile(r"(?m)^\s*##\s+(.+?)\s*$")


class MarkdownIngestor(Ingestor):
    name = "markdown"
    extensions = (".md", ".markdown")

    def ingest(self, path: Path) -> RawStory:
        raw = path.read_text(encoding="utf-8")
        text = clean_text(raw)

        h1s = list(_H1_RE.finditer(text))
        h2s = list(_H2_RE.finditer(text))

        # Preferred: one H1 = title; multiple H2 = chapters.
        # Fallback: multiple H1 = chapters.
        # Last resort: no headings = single chapter.
        if len(h1s) == 1 and len(h2s) >= 1:
            title = h1s[0].group(1).strip()
            # Body after H1 until first H2 is preface; attach to first chapter.
            chapters = self._split_by(text, h2s, offset_start=h1s[0].end())
        elif len(h1s) >= 2:
            title = guess_title_from_path(path)
            chapters = self._split_by(text, h1s)
        elif len(h1s) == 1:
            title = h1s[0].group(1).strip()
            body = text[h1s[0].end():].strip()
            chapters = [RawChapter(number=1, title=title, text=body)]
        else:
            title = guess_title_from_path(path)
            chapters = [RawChapter(number=1, title="Chapter 1", text=text.strip())]

        return RawStory(
            title=title,
            author="unknown",
            source_format="md",
            chapters=chapters,
        )

    @staticmethod
    def _split_by(
        text: str,
        matches: list[re.Match[str]],
        offset_start: int = 0,
    ) -> list[RawChapter]:
        chapters: list[RawChapter] = []
        # Body between offset_start and the first chapter heading is preface
        # text; append it to the first chapter so wording stays faithful.
        first_start = matches[0].start() if matches else len(text)
        preface = text[offset_start:first_start].strip()
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            title = m.group(1).strip()
            if i == 0 and preface:
                body = (preface + "\n\n" + body).strip()
            chapters.append(RawChapter(number=i + 1, title=title, text=body))
        return chapters
