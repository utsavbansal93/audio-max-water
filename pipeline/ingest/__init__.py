"""File-format ingestors — `file → RawStory` (no LLM, no network).

`pipeline/parse.py` consumes a `RawStory` and hands it to an `LLMProvider`
to produce `script.json`. The split keeps format-specific parsing
deterministic and cheap; the LLM only ever sees clean text.

Adding a format = one file here + one line in `get_ingestor`.
"""
from __future__ import annotations

from pathlib import Path

from .base import Ingestor, RawChapter, RawStory


def get_ingestor(path: Path) -> Ingestor:
    ext = path.suffix.lower()
    if ext in (".txt",):
        from .text_ingestor import TextIngestor
        return TextIngestor()
    if ext in (".md", ".markdown"):
        from .markdown_ingestor import MarkdownIngestor
        return MarkdownIngestor()
    if ext in (".docx", ".doc"):
        from .docx_ingestor import DocxIngestor
        return DocxIngestor()
    if ext in (".epub",):
        from .epub_ingestor import EpubIngestor
        return EpubIngestor()
    if ext in (".pdf",):
        from .pdf_ingestor import PdfIngestor
        return PdfIngestor()
    raise ValueError(
        f"Unsupported input format: {ext!r}. "
        f"Supported: .txt, .md, .docx, .epub, .pdf"
    )


def ingest(path: Path) -> RawStory:
    """Convenience wrapper: dispatch by extension and run."""
    return get_ingestor(path).ingest(path)


__all__ = ["Ingestor", "RawStory", "RawChapter", "get_ingestor", "ingest"]
