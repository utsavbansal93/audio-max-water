"""Plain `.txt` ingestor.

Treats the whole file as one chapter unless obvious chapter markers
(`Chapter N`, `CHAPTER N`, `Chapter One`, etc.) split it. Zero library
dependencies — stdlib only.
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


# Matches lines like "Chapter 1", "CHAPTER 12", "Chapter One: The Beginning",
# possibly followed by a colon + title on the same line.
_CHAPTER_RE = re.compile(
    r"(?im)^\s*chapter\s+"
    r"(?P<num>\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty)"
    r"\s*[:.\-\u2014\u2013]?\s*(?P<title>.*?)\s*$"
)

_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}


def _parse_chapter_num(token: str) -> int:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _WORD_TO_NUM.get(token, 1)


class TextIngestor(Ingestor):
    name = "text"
    extensions = (".txt",)

    def ingest(self, path: Path) -> RawStory:
        text = clean_text(path.read_text(encoding="utf-8"))
        chapters = self._split_chapters(text)
        return RawStory(
            title=guess_title_from_path(path),
            author="unknown",
            source_format="txt",
            chapters=chapters,
        )

    @staticmethod
    def _split_chapters(text: str) -> list[RawChapter]:
        matches = list(_CHAPTER_RE.finditer(text))
        if not matches:
            return [RawChapter(number=1, title="Chapter 1", text=text.strip())]

        chapters: list[RawChapter] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            num = _parse_chapter_num(m.group("num"))
            title = m.group("title").strip() or f"Chapter {num}"
            chapters.append(RawChapter(number=num, title=title, text=body))
        # If we found markers but no body before the first one, that's fine.
        # Renumber sequentially in case the source uses non-sequential IDs.
        for i, ch in enumerate(chapters, start=1):
            ch.number = i
        return chapters or [RawChapter(number=1, title="Chapter 1", text=text.strip())]
