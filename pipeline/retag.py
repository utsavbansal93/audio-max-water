"""Re-run LLM emotion annotation on an already-parsed script.json.

This is the targeted fix for a scene where listening reveals under- or
over-emoted lines.  Unlike re-parsing (which risks faithful-wording
divergence), re-tagging ONLY rewrites `line.emotion.*` — `line.text`
is never touched.

The faithful-wording validator is re-run after re-tagging to confirm that
the text content is unchanged.  If it diverges (which it should never, since
we write `line.text` back verbatim from the original), the process aborts.

Usage:
    python -m pipeline.retag --script build/<stem>/script.json --chapter 3
    python -m pipeline.retag --script build/<stem>/script.json  # all chapters

Optional: --provider anthropic|gemini (default: reads config.yaml)
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import yaml

from pipeline._errors import ParseError
from pipeline.schema import EmotionModel, ScriptModel
from pipeline.validate import check_faithful_wording


log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[1]

_RETAG_SYSTEM = """\
You are given a chapter from a script.json. Each line has a "text" field (DO NOT CHANGE)
and an "emotion" object. Your task is to revise ONLY the emotion fields: label, intensity
(0.0-1.0), pace (-1.0 to +1.0), and notes.

Rules:
1. Output the SAME JSON array of lines with the SAME "text" values verbatim.
2. Only change "label", "intensity", "pace", "notes" inside each "emotion" object.
3. Read the provided book_context to calibrate emotions to the full arc.
4. Return JSON only, no preamble.
"""


def _retag_chapter_lines(
    lines: list[dict],
    book_context: str,
    provider,
) -> list[dict]:
    user_prompt = (
        f"Book context: {book_context}\n\n"
        f"Chapter lines:\n{json.dumps(lines, ensure_ascii=False, indent=2)}"
    )
    raw = provider.complete(_RETAG_SYSTEM, user_prompt, max_tokens=8000)

    # Strip code fences if present.
    fence = re.match(r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)

    try:
        revised = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Re-tagger returned invalid JSON: {exc}") from exc

    if len(revised) != len(lines):
        raise ParseError(
            f"Re-tagger returned {len(revised)} lines but expected {len(lines)}"
        )

    # Enforce: text fields must be verbatim.
    for orig, new in zip(lines, revised):
        if orig["text"] != new.get("text"):
            raise ParseError(
                f"Re-tagger mutated text: {orig['text']!r} -> {new.get('text')!r}"
            )

    return revised


def retag(
    script_path: Path,
    chapter_numbers: list[int] | None,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
) -> None:
    from llm import get_provider

    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    prov_name = provider_name or cfg.get("llm_provider", "anthropic")
    provider = get_provider(prov_name)

    raw = json.loads(script_path.read_text())
    script = ScriptModel.model_validate(raw)

    source_md_path = script_path.parent / "source.md"
    if not source_md_path.exists():
        raise SystemExit(
            f"source.md not found at {source_md_path}. "
            "Re-tag requires the source file to re-validate faithful wording."
        )

    for ch in script.chapters:
        if chapter_numbers and ch.number not in chapter_numbers:
            continue

        print(f"Re-tagging chapter {ch.number}: {ch.title} ({len(ch.lines)} lines)…")
        lines_dicts = [
            {"text": ln.text, "emotion": ln.emotion.model_dump()}
            for ln in ch.lines
        ]

        try:
            revised = _retag_chapter_lines(lines_dicts, script.book_context, provider)
        except ParseError as exc:
            print(f"  ERROR: {exc} — skipping chapter {ch.number}")
            continue

        # Write emotion fields back; text is unchanged.
        for ln, rev in zip(ch.lines, revised):
            ln.emotion = EmotionModel.model_validate(rev["emotion"])

    if dry_run:
        print("Dry-run: no file written.")
        return

    updated = script.model_dump()
    script_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")

    # Re-validate faithful wording (text fields must be unchanged).
    source_md = source_md_path.read_text()
    errors = check_faithful_wording(script, source_md)
    if errors:
        print("WARNING: faithful-wording check found divergences after re-tag:")
        for e in errors:
            print(" ", e)
        print("Review and fix script.json manually; the emotions have been saved.")
    else:
        print(f"Done. {script_path} updated; faithful-wording check passed.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-run emotion annotation on script.json")
    ap.add_argument("--script", required=True, type=Path,
                    help="Path to script.json (e.g. build/Hyperthief/script.json)")
    ap.add_argument("--chapter", type=int, nargs="+", default=None,
                    help="Chapter number(s) to re-tag (default: all)")
    ap.add_argument("--provider", default=None,
                    help="LLM provider name (default: reads config.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print revised emotions without writing to disk")
    args = ap.parse_args()

    retag(args.script, args.chapter, provider_name=args.provider, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
