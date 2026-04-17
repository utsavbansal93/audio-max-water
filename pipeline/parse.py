"""LLM-driven parse step: RawStory → ScriptModel (script.json).

Before this module, parsing was a manual Claude-in-the-loop step: user
copied the story into Claude, pasted the system prompt, pasted the JSON
output into `build/script.json`. This module replaces that loop with
a programmatic LLM call, while preserving the faithful-wording contract
via the existing validator.

Flow:
  1. Load system prompt from `prompts/parse_story.md`.
  2. Render RawStory to canonical markdown (for both LLM input and the
     validator reference file).
  3. Call the configured `LLMProvider` with (system, user=source_md).
  4. Strip code fences, parse JSON, validate against `ScriptModel`.
  5. Run `check_faithful_wording` against the reference source file.
  6. On divergence, retry once with a targeted fix request.
  7. Write `script.json` and `source.md` to the build directory.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

from llm import LLMProvider, get_provider
from pipeline._errors import ParseError
from pipeline._events import ProgressCallback, ProgressEvent, emit
from pipeline.ingest import RawStory, ingest
from pipeline.schema import ScriptModel
from pipeline.validate import check_faithful_wording


log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_PATH = REPO / "prompts" / "parse_story.md"

_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def parse_raw_story(
    raw: RawStory,
    provider: LLMProvider,
    *,
    max_tokens: int = 16000,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    retry_on_wording_divergence: bool = True,
) -> tuple[ScriptModel, str]:
    """Parse `raw` into a ScriptModel via `provider`.

    Returns `(script, source_md)` where source_md is the canonical markdown
    used both as the LLM input and as the validator's reference text.
    The caller is responsible for writing both artifacts to disk.
    """
    system = prompt_path.read_text(encoding="utf-8")
    source_md = raw.to_source_md()

    log.info(
        "parse: %s (%d chars, %d words) via %s",
        raw.title, len(source_md), raw.total_words, provider.name,
    )

    t0 = time.perf_counter()
    response = provider.complete(
        system=system,
        user=source_md,
        max_tokens=max_tokens,
    )
    log.debug("parse: llm call 1 took %.1fs, response %d chars",
              time.perf_counter() - t0, len(response))
    script = _response_to_script(response)
    log.debug("parse: parsed %d chapters, %d total lines",
              len(script.chapters),
              sum(len(c.lines) for c in script.chapters))

    # Validate wording against the canonical source_md. We write it to a
    # temp path so we can reuse the existing file-based validator API.
    # Patch author / language from the ingestor when the LLM didn't
    # capture them (or got them wrong). Text-based author extraction in
    # the ingest layer is more reliable than trusting the LLM to spot
    # the byline — especially for PDF/DOCX where the source is noisy.
    if raw.author and raw.author != "unknown" and (
        not script.author or script.author.lower() == "unknown"
    ):
        script = script.model_copy(update={"author": raw.author})
    if raw.language and (not script.language or script.language == "en"):
        if raw.language != "en":
            script = script.model_copy(update={"language": raw.language})

    errors = _validate_against_source(script, source_md)
    if errors and retry_on_wording_divergence:
        log.warning("parse: faithful-wording divergence on first pass, retrying")
        for line in errors:
            log.debug("  %s", line)
        # Targeted retry: include the divergence context so the model fixes
        # exactly the segment that drifted, not the whole thing.
        followup = _build_retry_prompt(errors, source_md)
        t1 = time.perf_counter()
        response2 = provider.complete(
            system=system,
            user=followup,
            max_tokens=max_tokens,
        )
        log.debug("parse: llm call 2 (retry) took %.1fs", time.perf_counter() - t1)
        script = _response_to_script(response2)
        errors = _validate_against_source(script, source_md)

    if errors:
        log.error("parse: faithful-wording validation FAILED after retry")
        for line in errors:
            log.error("  %s", line)
        raise ParseError(
            "Faithful-wording validation failed after retry:\n"
            + "\n".join(errors)
        )

    # Post-parse normalization: split any lumped dialogue-attribution tags
    # (e.g. `"Hey!" he said. "Um, happy birthday?"` on Rig's line) into
    # separate narrator lines so "he said" renders in the narrator's voice,
    # not the character's. Preserves faithful-wording by construction, but
    # we re-validate defensively in case an edge case slips through.
    from pipeline.normalize import canonicalize_speakers, split_lumped_dialogue_tags
    script, n_canon = canonicalize_speakers(script)
    if n_canon:
        log.info("parse: canonicalized %d speaker key(s) to first-seen casing", n_canon)
    script, n_splits = split_lumped_dialogue_tags(script)
    if n_splits:
        log.info("parse: split %d lumped dialogue tags post-parse", n_splits)
        post_errors = _validate_against_source(script, source_md)
        if post_errors:
            raise ParseError(
                "Dialogue-tag split broke faithful wording:\n" + "\n".join(post_errors)
            )

    log.info("parse: OK — %d chapters, %d lines  author=%r  lang=%r",
             len(script.chapters),
             sum(len(c.lines) for c in script.chapters),
             script.author, script.language)
    return script, source_md


def _response_to_script(response: str) -> ScriptModel:
    text = response.strip()
    m = _CODE_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # Some providers emit stray prose before/after the JSON object; try to
    # slice from the first '{' to the matching final '}' if direct parse fails.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ParseError(
                "LLM response was not parseable JSON and contains no "
                "balanced braces.\nResponse head:\n" + text[:500]
            )
        data = json.loads(text[start: end + 1])
    return ScriptModel.model_validate(data)


def _validate_against_source(script: ScriptModel, source_md: str) -> list[str]:
    """Run the faithful-wording check against `source_md` as the reference.

    `check_faithful_wording` expects a file path; stage source_md in a
    temp file so we don't need to duplicate its normalization logic here.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(source_md)
        tmp_path = Path(tmp.name)
    try:
        return check_faithful_wording(script, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _build_retry_prompt(errors: list[str], source_md: str) -> str:
    """Craft a focused follow-up for the LLM so it fixes the divergence."""
    err_text = "\n".join(errors)
    return (
        "Your previous JSON output diverged from the source wording. A "
        "downstream validator found the following mismatch:\n\n"
        f"{err_text}\n\n"
        "Please emit the FULL script JSON again, with every line.text "
        "byte-verbatim from the source below. Do not paraphrase, do not "
        "add or remove words. Preserve punctuation exactly. Output ONLY "
        "the JSON object, no code fences, no prose.\n\n"
        "--- Source ---\n"
        f"{source_md}"
    )


# --- orchestrator helper ---------------------------------------------------


def parse_to_disk(
    input_path: Path,
    build_dir: Path,
    provider_name: str = "anthropic",
    *,
    model: str | None = None,
    max_tokens: int = 16000,
    on_progress: ProgressCallback = None,
) -> tuple[ScriptModel, Path, Path]:
    """Ingest + parse + write script.json and source.md to `build_dir`.

    Returns (script, script_path, source_path). Safe to call repeatedly:
    if `script.json` and `source.md` already exist and the source.md
    matches what we'd produce from the current input, we skip the LLM
    call and just return the cached result.

    `on_progress` is invoked with `ingest:*` and `parse:*` stage events
    so the UI can update its stage tracker.
    """
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    script_path = build_dir / "script.json"
    source_path = build_dir / "source.md"

    log.info("ingest: %s", input_path)
    emit(on_progress, ProgressEvent(
        stage="ingest", phase="start",
        message=f"reading {input_path.name}",
    ))
    raw = ingest(input_path)
    log.info("ingest: OK — format=%s, %d chapters, %d words, author=%r, lang=%r",
             raw.source_format, len(raw.chapters), raw.total_words,
             raw.author, raw.language)

    # If the ingestor extracted a cover image, persist it to build_dir
    # so package() can pick it up without the orchestrator needing to
    # pass bytes through kwargs.
    cover_bytes = raw.metadata.get("cover_bytes")
    cover_ext = raw.metadata.get("cover_ext", "jpg")
    if cover_bytes:
        cover_path_from_source = build_dir / f"source_cover.{cover_ext}"
        cover_path_from_source.write_bytes(cover_bytes)
        log.info("ingest: extracted cover (%s, %d bytes) → %s",
                 cover_ext, len(cover_bytes), cover_path_from_source)

    emit(on_progress, ProgressEvent(
        stage="ingest", phase="done",
        message=f"read {raw.source_format} · {len(raw.chapters)} chapter(s), "
                f"{raw.total_words} words"
                + (" · cover found" if cover_bytes else ""),
    ))
    fresh_source = raw.to_source_md()

    # Cache hit: same source → same script. Re-run only on change.
    if script_path.exists() and source_path.exists():
        try:
            cached_source = source_path.read_text(encoding="utf-8")
            if cached_source == fresh_source:
                cached = ScriptModel.model_validate(
                    json.loads(script_path.read_text(encoding="utf-8"))
                )
                log.info("parse: cache hit — skipping LLM call (%s)", script_path)
                emit(on_progress, ProgressEvent(
                    stage="parse", phase="done",
                    message=f"reused cached script ({len(cached.chapters)} chapters)",
                ))
                return cached, script_path, source_path
        except Exception as e:
            log.debug("parse: cache invalid (%s) — re-parsing", e)

    emit(on_progress, ProgressEvent(
        stage="parse", phase="start",
        message=f"asking {provider_name} to structure the script",
    ))

    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model
    provider = get_provider(provider_name, **provider_kwargs)

    script, source_md = parse_raw_story(raw, provider, max_tokens=max_tokens)

    source_path.write_text(source_md, encoding="utf-8")
    script_path.write_text(
        json.dumps(script.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    return script, script_path, source_path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse an input file into script.json via an LLM provider."
    )
    ap.add_argument("--in", dest="input", required=True, type=Path,
                    help="Input file (.txt/.md/.docx/.epub/.pdf)")
    ap.add_argument("--build", default=None, type=Path,
                    help="Build directory (default: build/<input_stem>)")
    ap.add_argument("--provider", default=None,
                    help="LLM provider (anthropic | gemini). "
                         "Default: config.yaml llm.provider")
    ap.add_argument("--model", default=None,
                    help="Override provider default model id")
    args = ap.parse_args()

    from pipeline.config import load_config
    cfg = load_config()
    provider = args.provider or cfg.get("llm", {}).get("provider", "anthropic")
    model = args.model or cfg.get("llm", {}).get("model")
    max_tokens = cfg.get("llm", {}).get("max_tokens", 16000)

    build = args.build or (REPO / "build" / args.input.stem)
    script, script_path, source_path = parse_to_disk(
        args.input, build, provider, model=model, max_tokens=max_tokens
    )
    print(f"parsed: {args.input.name}")
    print(f"  title:    {script.title}")
    print(f"  chapters: {len(script.chapters)}")
    print(f"  lines:    {sum(len(c.lines) for c in script.chapters)}")
    print(f"  script:   {script_path}")
    print(f"  source:   {source_path}")


if __name__ == "__main__":
    main()
