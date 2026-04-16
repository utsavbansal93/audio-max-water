"""EPUB ingestor (ebooklib + BeautifulSoup).

Walks the EPUB spine, strips HTML to text, uses the TOC for chapter
titles. Handles EPUB2 and EPUB3. Ignores images, fonts, styles —
audiobooks don't need them.

Front-matter filtering: the listener doesn't want to hear the cover
page, copyright notice, or a verbal reading of the table of contents.
This ingestor detects and skips those via three signals:
  1. `epub:type` attribute on the document root (EPUB3 standard vocab
     e.g. "cover", "titlepage", "copyright-page", "toc", "colophon",
     "imprint", "index").
  2. Filename patterns (`cover.xhtml`, `copyright.xhtml`, `toc.xhtml`,
     `titlepage.xhtml`, `index.xhtml`, `colophon.xhtml`).
  3. TOC entry titles matching known front-matter names ("Cover",
     "Copyright", "Title Page", "Contents", "Index").

Preface, foreword, dedication, epigraph, introduction — the things a
reader would actually begin with — are KEPT. This matches the user's
requirement: start from the first piece of real content.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

from .base import (
    Ingestor,
    RawChapter,
    RawStory,
    clean_text,
    guess_title_from_path,
)


# EPUB3 `epub:type` values classified as front-matter we should skip.
# (Per the EPUB 3.3 Structural Semantics Vocabulary.)
_FRONTMATTER_EPUB_TYPES = {
    "cover",
    "frontispiece",
    "titlepage",
    "halftitlepage",
    "copyright-page",
    "imprint",
    "colophon",
    "toc",            # table of contents
    "landmarks",
    "loa",            # list of audio
    "lof",            # list of figures
    "lot",            # list of tables
    "page-list",
    "index",
    "index-headnotes",
    "index-legend",
    "index-group",
    "index-entry-list",
    "index-entry",
    "index-term",
    "index-editor-note",
    "index-locator",
    "index-xref-preferred",
    "index-xref-related",
    "errata",
    "publisher-logo",
    "series-page",
    "bibliography",
    "appendix",
    "glossary",
    "acknowledgments",  # debatable; keep skipped-by-default (often dense + dry)
    "notice",
    "other-credits",
    "contributors",
}

# Everything with these types is clearly main content; keep regardless
# of other signals.
_BODY_EPUB_TYPES = {
    "bodymatter",
    "chapter",
    "part",
    "volume",
    "preface",
    "foreword",
    "prologue",
    "epilogue",
    "introduction",
    "dedication",
    "epigraph",
    "afterword",
    "conclusion",
}

_FRONTMATTER_FILENAME_RE = re.compile(
    r"(cover|titlepage|title-page|copyright|colophon|imprint|"
    r"toc|contents|landmarks|loa|lof|lot|index|page-?list|"
    r"errata|publisher|series|bibliography|appendix|glossary|"
    r"acknowledg|notice|dedication-page)",
    re.IGNORECASE,
)

_FRONTMATTER_TITLE_RE = re.compile(
    r"^\s*(cover|title page|copyright|colophon|imprint|"
    r"table of contents|contents|toc|index|bibliography|appendix|"
    r"glossary|landmarks|list of (figures|tables|audio)|about the author|"
    r"other books?|acknowledgments?|notes?)\s*$",
    re.IGNORECASE,
)

# Filenames / titles that are ALWAYS body content (override frontmatter signals).
_BODY_FILENAME_RE = re.compile(
    r"(dedic|preface|foreword|introduction|prologue|epigraph|"
    r"epilogue|afterword|chapter|chap|part|book|section)",
    re.IGNORECASE,
)

_BODY_TITLE_RE = re.compile(
    r"^\s*(dedication|preface|foreword|introduction|prologue|"
    r"epigraph|epilogue|afterword|chapter\b.*|part\b.*|book\b.*)\s*$",
    re.IGNORECASE,
)


class EpubIngestor(Ingestor):
    name = "epub"
    extensions = (".epub",)

    def ingest(self, path: Path) -> RawStory:
        try:
            from ebooklib import epub, ITEM_DOCUMENT  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="ebooklib",
                feature=".epub ingest",
                install=".venv/bin/pip install -e '.[ingest]'",
                required=True,
            ) from e
        try:
            from bs4 import BeautifulSoup  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="beautifulsoup4",
                feature=".epub ingest (HTML parsing)",
                install=".venv/bin/pip install -e '.[ingest]'",
                required=True,
            ) from e

        # ebooklib warns about future deprecations on load; noisy for users.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path))

        # Metadata
        title = self._meta_first(book, "title") or guess_title_from_path(path)
        author = self._meta_first(book, "creator") or "unknown"

        # Map spine item IDs → TOC titles where possible.
        toc_titles = self._toc_title_map(book)

        # Walk spine in reading order, skipping front-matter.
        chapters: list[RawChapter] = []
        chapter_num = 0
        skipped: list[str] = []  # for logging

        for item_id, _linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ITEM_DOCUMENT:
                continue

            soup = BeautifulSoup(item.get_content(), "html.parser")

            # Drop non-content tags that leak junk into text extraction.
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()

            # Normalize <hr> and common scene-break divs to "---".
            for hr in soup.find_all("hr"):
                hr.replace_with("\n\n---\n\n")

            # Chapter title: prefer TOC, then <h1>/<h2>, then fallback.
            toc_title = toc_titles.get(item.file_name) or toc_titles.get(item_id)
            h = soup.find(["h1", "h2"])
            heading_text = h.get_text(strip=True) if h else ""
            ch_title = toc_title or heading_text or f"Chapter {chapter_num + 1}"

            # --- front-matter filter ------------------------------------
            # Gather epub:type values anywhere in the document.
            epub_types = _collect_epub_types(soup)
            fname = item.file_name or ""
            reason = _classify_frontmatter(
                epub_types=epub_types,
                filename=fname,
                title=ch_title,
            )
            if reason == "skip":
                skipped.append(f"{fname} ({ch_title!r})")
                continue
            # If reason == "keep" or "unknown" we proceed.

            # Extract paragraphs (keep paragraph breaks for the parser).
            paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            if not paragraphs:
                # Some EPUBs put text in <div> or directly in <body>.
                paragraphs = [soup.get_text(" ", strip=True)]
            body_raw = "\n\n".join(p for p in paragraphs if p)
            body = clean_text(body_raw)
            if not body.strip():
                continue

            # Content heuristic: if epub:type was unknown AND the body is
            # very short (< 300 chars), this is probably front-matter too
            # (a short dedication page with just 2 lines is legit; a
            # one-line "For more books, visit…" page is not).
            if reason == "unknown" and len(body) < 140 and not epub_types:
                # Short + no metadata — likely promotional / boilerplate.
                # We still keep it if the title or filename looks like
                # dedication / epigraph.
                if not _looks_like_short_body_content(ch_title, fname):
                    skipped.append(f"{fname} (short, {len(body)} chars)")
                    continue

            chapter_num += 1
            chapters.append(
                RawChapter(number=chapter_num, title=ch_title, text=body)
            )

        if skipped:
            import warnings as _w
            _w.warn(
                f"epub ingest: skipped {len(skipped)} front-matter / "
                f"non-content section(s): {', '.join(skipped[:5])}"
                + ("…" if len(skipped) > 5 else ""),
                stacklevel=2,
            )

        if not chapters:
            chapters = [RawChapter(number=1, title="Chapter 1", text="")]

        return RawStory(
            title=title,
            author=author,
            source_format="epub",
            chapters=chapters,
        )

    @staticmethod
    def _meta_first(book, name: str) -> str:
        meta = book.get_metadata("http://purl.org/dc/elements/1.1/", name)
        if not meta:
            return ""
        first = meta[0]
        return (first[0] or "").strip() if first else ""

    @staticmethod
    def _toc_title_map(book) -> dict[str, str]:
        """Flatten TOC entries into {href_or_id: title}."""
        from ebooklib.epub import Link, Section  # type: ignore[import-not-found]

        out: dict[str, str] = {}

        def walk(items):
            for entry in items:
                if isinstance(entry, tuple) and len(entry) == 2:
                    section, children = entry
                    if isinstance(section, (Link, Section)):
                        out[section.href.split("#")[0]] = section.title
                    walk(children)
                elif isinstance(entry, Link):
                    out[entry.href.split("#")[0]] = entry.title
                elif isinstance(entry, Section):
                    pass  # sections without hrefs — skip

        walk(book.toc)
        return out


# --- module-level front-matter filtering helpers ---------------------------


def _collect_epub_types(soup) -> set[str]:
    """Return the set of distinct `epub:type` token values in the document."""
    out: set[str] = set()
    for el in soup.find_all(attrs={"epub:type": True}):
        raw = el.get("epub:type", "") or ""
        for tok in raw.split():
            out.add(tok.strip().lower())
    # BeautifulSoup's html.parser sometimes lowercases the attribute name.
    for el in soup.find_all(attrs={"type": True}):
        raw = el.get("type", "") or ""
        for tok in raw.split():
            t = tok.strip().lower()
            # only accept if it's one of the vocab values we recognize
            if t in _FRONTMATTER_EPUB_TYPES or t in _BODY_EPUB_TYPES:
                out.add(t)
    return out


def _classify_frontmatter(
    *, epub_types: set[str], filename: str, title: str,
) -> str:
    """Decide whether to keep, skip, or fall through to content heuristics.

    Returns one of:
      - "skip":    definitely front-matter; drop it
      - "keep":    definitely body content; keep it
      - "unknown": no strong signal — let the caller decide based on length

    Resolution order (strongest signal wins):
      1. epub:type in body vocab → keep
      2. epub:type in frontmatter vocab → skip
      3. filename matches body list (dedic/preface/intro/chapter/…) → keep
      4. title matches body list → keep
      5. filename matches frontmatter list (cover/toc/copyright/…) → skip
      6. title matches frontmatter list → skip
      7. otherwise → unknown
    """
    # Explicit epub:type beats everything.
    if any(t in _BODY_EPUB_TYPES for t in epub_types):
        return "keep"
    if any(t in _FRONTMATTER_EPUB_TYPES for t in epub_types):
        return "skip"

    # Body signals (dedication, preface, etc.) take precedence over
    # frontmatter checks — per user: dedication, introduction, foreword
    # ARE the main content; don't skip them.
    if _BODY_FILENAME_RE.search(filename or ""):
        return "keep"
    if title and _BODY_TITLE_RE.match(title):
        return "keep"

    # Frontmatter signals (cover, toc, copyright, index, …).
    if _FRONTMATTER_FILENAME_RE.search(filename or ""):
        return "skip"
    if title and _FRONTMATTER_TITLE_RE.match(title):
        return "skip"

    return "unknown"


def _looks_like_short_body_content(title: str, filename: str) -> bool:
    """A short document whose title/filename suggests dedication or
    epigraph — legit body content (user asked us to KEEP dedication)."""
    needle = f"{title} {filename}".lower()
    return any(w in needle for w in ("dedic", "epigraph", "preface",
                                     "foreword", "introduction",
                                     "prologue"))
