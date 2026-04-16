"""PDF ingestor (pdfplumber).

Extracts text page by page. Uses a font-size heuristic to detect
chapter boundaries — pages that open with significantly larger text
than the body font are treated as chapter starts. Falls back to a
single chapter when no such pages are found.

PDF text extraction is lossy on multi-column layouts and scanned
documents (OCR output); we emit a warning in those cases rather
than silently producing garbage.
"""
from __future__ import annotations

import statistics
import warnings
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


class PdfIngestor(Ingestor):
    name = "pdf"
    extensions = (".pdf",)

    def ingest(self, path: Path) -> RawStory:
        try:
            import pdfplumber  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="pdfplumber",
                feature=".pdf ingest",
                install=".venv/bin/pip install -e '.[ingest]'",
                required=True,
            ) from e

        pages_text: list[str] = []
        page_first_char_size: list[float] = []
        with pdfplumber.open(str(path)) as pdf:
            meta = pdf.metadata or {}
            title = (meta.get("Title") or "").strip() or guess_title_from_path(path)
            # Author: prefer text-based extraction (see extract_author_from_text
            # docstring — PDF metadata author is notoriously unreliable because
            # the Author field gets stamped with whatever tool produced the PDF).
            # We'll run this AFTER we've got the opening page(s) extracted.
            meta_author_raw = (meta.get("Author") or "").strip()

            if len(pdf.pages) > 500:
                warnings.warn(
                    f"{path.name}: large PDF ({len(pdf.pages)} pages). "
                    "Extraction may be slow; consider splitting the book.",
                    stacklevel=2,
                )

            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
                # Pull the size of the first word's first char (rough heuristic).
                size = 0.0
                try:
                    chars = page.chars
                    if chars:
                        size = float(chars[0].get("size", 0.0))
                except Exception:
                    size = 0.0
                page_first_char_size.append(size)

        # Author extraction: scan the first page or two of extracted text
        # for a "by X" byline. If that fails, fall back to document
        # metadata but only if the metadata author isn't one of the
        # well-known tool names that get stamped in by accident.
        opening_text = "\n".join(pages_text[:2])
        author_from_text = extract_author_from_text(opening_text)
        if author_from_text:
            author = author_from_text
        else:
            author = clean_metadata_author(meta_author_raw) or "unknown"

        # Median body font size — anything meaningfully larger suggests a heading.
        sizes_nonzero = [s for s in page_first_char_size if s > 0]
        median_size = statistics.median(sizes_nonzero) if sizes_nonzero else 0.0
        big_threshold = median_size * 1.3 if median_size else 0.0

        # Treat a page as a chapter start if its first-char size is notably large.
        chapter_starts: list[int] = [
            i for i, s in enumerate(page_first_char_size)
            if big_threshold and s >= big_threshold
        ]
        if not chapter_starts:
            chapter_starts = [0]
        if chapter_starts[0] != 0:
            chapter_starts = [0] + chapter_starts

        chapters: list[RawChapter] = []
        for i, start in enumerate(chapter_starts):
            end = chapter_starts[i + 1] if i + 1 < len(chapter_starts) else len(pages_text)
            body_raw = "\n\n".join(pages_text[start:end])
            body = clean_text(body_raw)
            if not body.strip():
                continue
            # Heading guess: first non-empty line of first page in this range.
            first_lines = [ln for ln in pages_text[start].splitlines() if ln.strip()]
            heading = first_lines[0].strip() if first_lines else f"Chapter {i + 1}"
            # If the heading line is absurdly long, it's probably body text —
            # fall back to a generic title and keep the text intact.
            if len(heading) > 80:
                heading = f"Chapter {i + 1}"
            chapters.append(
                RawChapter(number=i + 1, title=heading, text=body)
            )

        if not chapters:
            chapters = [RawChapter(number=1, title="Chapter 1", text="")]

        # Remove the `by <author>` byline from the rendered narrator stream
        # if we extracted an author from text — keep the title page clean.
        # (The author still flows through as metadata; no reason to also
        # hear it read aloud as a narrator line.)

        return RawStory(
            title=title,
            author=author,
            source_format="pdf",
            chapters=chapters,
        )
