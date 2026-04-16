"""Microsoft Word `.docx` ingestor (python-docx).

Uses the document's Heading 1 / Heading 2 style names to detect chapter
boundaries. Falls back to a single chapter if no headings are present.

`.doc` (legacy Word binary) is not supported — users should export to
`.docx` first. We match `.doc` only to give a clear error message.
"""
from __future__ import annotations

from pathlib import Path

from .base import (
    Ingestor,
    RawChapter,
    RawStory,
    clean_metadata_author,
    clean_text,
    extract_author_from_text,
    guess_title_from_path,
)


class DocxIngestor(Ingestor):
    name = "docx"
    extensions = (".docx", ".doc")

    def ingest(self, path: Path) -> RawStory:
        if path.suffix.lower() == ".doc":
            raise RuntimeError(
                f"{path.name}: legacy .doc format not supported. "
                "Open in Word and save as .docx, or convert with "
                "`libreoffice --headless --convert-to docx <file>`."
            )
        try:
            import docx  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="python-docx",
                feature=".docx ingest",
                install=".venv/bin/pip install -e '.[ingest]'",
                required=True,
            ) from e

        doc = docx.Document(str(path))

        # Title: core properties are usually reliable for title.
        props = doc.core_properties
        title = (props.title or "").strip() or guess_title_from_path(path)
        # Author: core_properties.author is notoriously wrong on DOCX —
        # it reflects whoever's computer last saved the file, not the
        # book's real author. Extract from text first; use metadata only
        # as a ban-listed fallback.
        meta_author_raw = (props.author or "").strip()

        # Walk paragraphs, splitting on Heading 1 / Heading 2.
        chapters: list[RawChapter] = []
        current_title = "Chapter 1"
        current_lines: list[str] = []
        chapter_num = 0

        def flush() -> None:
            nonlocal chapter_num, current_lines, current_title
            if not current_lines:
                return
            chapter_num += 1
            body = clean_text("\n\n".join(current_lines))
            chapters.append(
                RawChapter(number=chapter_num, title=current_title, text=body)
            )
            current_lines = []

        for para in doc.paragraphs:
            style_name = (para.style.name or "").strip() if para.style else ""
            text = para.text.strip()
            if not text:
                continue
            if style_name in ("Heading 1", "Heading 2", "Title"):
                flush()
                current_title = text
            else:
                current_lines.append(text)

        flush()

        if not chapters:
            # No paragraphs found — fall back to an empty single chapter rather
            # than erroring, so the user gets a useful message downstream.
            chapters = [RawChapter(number=1, title="Chapter 1", text="")]

        # Author extraction: text first, then ban-listed metadata.
        opening_text = chapters[0].text if chapters else ""
        author_from_text = extract_author_from_text(opening_text)
        if author_from_text:
            author = author_from_text
        else:
            author = clean_metadata_author(meta_author_raw) or "unknown"

        return RawStory(
            title=title,
            author=author,
            source_format="docx",
            chapters=chapters,
        )
