"""End-to-end pipeline orchestrator: file → audiobook.

Chains: ingest → parse → cast (auto-propose) → render → qa → package.

Replaces the prior manual Claude-in-the-loop workflow. Safe to re-run:
every stage caches where it can, so subsequent renders of the same input
only do the work that changed.

Usage:
    python -m pipeline.run \\
        --in story.pdf \\
        --format m4b \\
        --cover cover.jpg \\
        --out out/

Missing-dependency policy:
  - REQUIRED features (ingest for a format you used, parse, render, package):
    hard error with the exact install command, non-zero exit.
  - OPTIONAL features (Whisper QA): log a warning, skip the step, continue.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import yaml

from pipeline._errors import ConfigurationError, MissingDependency, PipelineError
from pipeline._events import ProgressCallback, ProgressEvent, emit
from pipeline._logging import configure_logging, log_exception
from pipeline.config import load_config
from pipeline.schema import CastModel, ScriptModel


REPO = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)


def _default_build_dir(input_path: Path) -> Path:
    return REPO / "build" / input_path.stem


def _find_source_cover(build_dir: Path) -> Path | None:
    """Return the path to a source-extracted cover image if one exists
    at `<build_dir>/source_cover.*`. Written by parse_to_disk when the
    ingestor found a cover in the source file."""
    for ext in ("jpg", "jpeg", "png", "gif", "webp"):
        p = build_dir / f"source_cover.{ext}"
        if p.exists():
            return p
    return None


def _write_cast(cast: CastModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cast.model_dump(), indent=2) + "\n")


def _auto_cast(
    script_path: Path,
    cast_path: Path,
    samples_dir: Path,
    backend_name: str,
) -> CastModel:
    """Propose + auto-approve a cast. Samples are written to `samples_dir`
    so the user can still listen and swap voices later if they want."""
    from pipeline.cast import load_cast, propose

    if cast_path.exists():
        log.info("cast: reusing existing %s", cast_path)
        return load_cast(cast_path)

    log.info("cast: proposing voices with backend=%s", backend_name)
    cast, proposals = propose(script_path, samples_dir, backend_name)
    _write_cast(cast, cast_path)
    for character, top in proposals.items():
        ranked = ", ".join(f"{i+1}.{v.display_name}" for i, v in enumerate(top))
        log.debug("  %s → %s", character, ranked)
    log.info("cast: wrote %s (auto-approved rank-1 per character)", cast_path)
    return cast


def _run_qa(script_path: Path, build_dir: Path, chapter_numbers: list[int],
            enable_whisper: bool) -> tuple[int, int]:
    """Returns (passing_lines, total_lines) across all chapters."""
    from pipeline.qa import scan_chapter, whisper_roundtrip

    total_ok = 0
    total = 0
    for ch_num in chapter_numbers:
        results = scan_chapter(script_path, ch_num, build_dir)
        ok = sum(1 for r in results if r.ok())
        total_ok += ok
        total += len(results)
        log.info("qa: chapter %02d — %d/%d lines OK", ch_num, ok, len(results))
        for r in results:
            if not r.ok():
                log.warning("  ch%02d line %02d [%s]: %s", ch_num, r.idx, r.speaker,
                            "; ".join(r.issues))

    if enable_whisper:
        script = ScriptModel.model_validate(json.loads(script_path.read_text()))
        try:
            for ch in script.chapters:
                mp3 = build_dir / f"ch{ch.number:02d}" / f"chapter_{ch.number:02d}.mp3"
                if not mp3.exists():
                    continue
                expected = " ".join(line.text for line in ch.lines)
                ratio, divergences = whisper_roundtrip(mp3, expected)
                log.info("qa: whisper ch%02d similarity %.3f", ch.number, ratio)
                if ratio < 0.92:
                    log.warning("  whisper similarity below 0.92 threshold")
                    for d in divergences:
                        log.debug("  %s", d)
        except MissingDependency as e:
            log.warning("qa: whisper skipped — %s", e.package)
            log.info("     to enable: %s", e.install)
    return total_ok, total


def run(
    *,
    input_path: Path,
    out_dir: Path,
    build_dir: Path,
    format: str = "m4b",
    backend: str | None = None,
    provider: str | None = None,
    provider_model: str | None = None,
    cast_path: Path | None = None,
    cover_path: Path | None = None,
    enable_whisper: bool = True,
    enable_qa: bool = True,
    on_progress: ProgressCallback = None,
) -> Path:
    """Run the full pipeline. Returns the final output path."""
    from pipeline._memory import require_free
    from pipeline.parse import parse_to_disk
    from pipeline.render import render_all
    from pipeline.package import package

    cfg = load_config(build_dir)
    backend_name = backend or cfg.get("backend") or "mlx-kokoro"
    provider_name = provider or cfg.get("llm", {}).get("provider", "anthropic")
    provider_model = provider_model or cfg.get("llm", {}).get("model")
    max_tokens = cfg.get("llm", {}).get("max_tokens", 16000)
    cover_path = cover_path or (
        Path(cfg["output"]["cover_path"])
        if cfg.get("output", {}).get("cover_path") else None
    )

    log.info("run: input=%s format=%s backend=%s provider=%s",
             input_path, format, backend_name, provider_name)

    # Memory watchdog before any model loads.
    require_free(min_gb=4.0 if enable_whisper else 3.5, backend=backend_name)

    # --- Stage 1: ingest + parse ---------------------------------------
    t0 = time.perf_counter()
    script, script_path, source_path = parse_to_disk(
        input_path=input_path,
        build_dir=build_dir,
        provider_name=provider_name,
        model=provider_model,
        max_tokens=max_tokens,
        on_progress=on_progress,
    )
    log.info("stage ingest+parse: %.1fs → %s", time.perf_counter() - t0, script_path)
    emit(on_progress, ProgressEvent(
        stage="parse", phase="done",
        message=f"parsed {len(script.chapters)} chapter(s), "
                f"{sum(len(c.lines) for c in script.chapters)} lines",
    ))

    # --- Stage 2: cast -------------------------------------------------
    cast_path = cast_path or (build_dir / "cast.json")
    samples_dir = build_dir / "cast_samples"
    emit(on_progress, ProgressEvent(stage="cast", phase="start", message="proposing voices"))
    t0 = time.perf_counter()
    _auto_cast(script_path, cast_path, samples_dir, backend_name)
    log.info("stage cast: %.1fs", time.perf_counter() - t0)
    emit(on_progress, ProgressEvent(stage="cast", phase="done", message="voices assigned"))

    # --- Stage 3: render -----------------------------------------------
    emit(on_progress, ProgressEvent(stage="render", phase="start", message="loading voice engine"))
    t0 = time.perf_counter()
    chapter_mp3s = render_all(
        script_path=script_path,
        cast_path=cast_path,
        backend_name=backend_name,
        build_dir=build_dir,
        on_progress=on_progress,
    )
    log.info("stage render: %.1fs → %d chapter MP3s",
             time.perf_counter() - t0, len(chapter_mp3s))

    # --- Stage 4: QA (optional) ---------------------------------------
    if enable_qa:
        t0 = time.perf_counter()
        ok, total = _run_qa(
            script_path, build_dir,
            [ch.number for ch in script.chapters],
            enable_whisper,
        )
        log.info("stage qa: %.1fs — %d/%d lines OK", time.perf_counter() - t0, ok, total)
    else:
        log.info("stage qa: SKIPPED (--no-qa)")

    # --- Stage 5: package ---------------------------------------------
    emit(on_progress, ProgressEvent(stage="package", phase="start", message=f"building .{format}"))
    t0 = time.perf_counter()
    # If the user didn't pass --cover, use the source-extracted cover
    # (written by parse_to_disk when the ingestor found one). Explicit
    # user choice always wins.
    effective_cover = cover_path or _find_source_cover(build_dir)
    # Author + language come from the parsed script, which was patched
    # with ingestor-detected values in parse.py.
    out_path = package(
        script_path=script_path,
        chapter_mp3s=chapter_mp3s,
        out_dir=out_dir,
        format=format,  # type: ignore[arg-type]
        build_dir=build_dir,
        title=script.title,
        author=(script.author if script.author and script.author != "unknown" else None),
        language=script.language or "en",
        cover_path=effective_cover,
    )
    log.info("stage package: %.1fs → %s", time.perf_counter() - t0, out_path)
    emit(on_progress, ProgressEvent(
        stage="package", phase="done",
        message=f"wrote {out_path.name}",
        extra={"output_path": str(out_path)},
    ))
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="pipeline.run",
        description="End-to-end: any text file → audiobook",
    )
    ap.add_argument("--in", dest="input", required=True, type=Path,
                    help="Input file (.txt | .md | .docx | .epub | .pdf)")
    ap.add_argument("--out", default=REPO / "out", type=Path,
                    help="Output directory for the final artifact")
    ap.add_argument("--build", default=None, type=Path,
                    help="Build directory (default: build/<input-stem>)")
    ap.add_argument("--format", default=None, choices=["m4b", "epub3"],
                    help="Output format (default: config.yaml output.format)")
    ap.add_argument("--cover", default=None, type=Path,
                    help="Optional cover image (JPG/PNG)")
    ap.add_argument("--backend", default=None,
                    help="TTS backend (default: config.yaml backend)")
    ap.add_argument("--provider", default=None,
                    help="LLM provider for parse (anthropic | gemini). "
                         "Default: config.yaml llm.provider")
    ap.add_argument("--model", default=None,
                    help="Override provider default model")
    ap.add_argument("--cast", default=None, type=Path,
                    help="Existing cast.json to reuse (skips auto-propose)")
    ap.add_argument("--no-whisper", action="store_true",
                    help="Skip Whisper round-trip QA (faster; still runs signal QA)")
    ap.add_argument("--no-qa", action="store_true",
                    help="Skip QA entirely")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="DEBUG-level console logging")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Warnings and errors only on console")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    build_dir = args.build or _default_build_dir(args.input)
    log_path = configure_logging(
        build_dir=build_dir, verbose=args.verbose, quiet=args.quiet
    )
    if log_path:
        log.info("run: logging to %s", log_path)

    # Load .env (API keys) early. Existing shell env wins.
    from pipeline._env import load_default_env
    added = load_default_env()
    if added:
        log.debug("loaded %d env vars from .env", added)

    # Fall back to config.yaml for format default.
    cfg = load_config()
    format_ = args.format or cfg.get("output", {}).get("format", "m4b")

    try:
        out_path = run(
            input_path=args.input,
            out_dir=args.out,
            build_dir=build_dir,
            format=format_,
            backend=args.backend,
            provider=args.provider,
            provider_model=args.model,
            cast_path=args.cast,
            cover_path=args.cover,
            enable_whisper=not args.no_whisper,
            enable_qa=not args.no_qa,
        )
    except MissingDependency as e:
        # Required missing dep: hard fail with actionable message.
        log.error("%s", e)
        log.error("    fix: %s", e.install)
        raise SystemExit(2)
    except ConfigurationError as e:
        # User configuration (missing env var, bad flag combination).
        log.error("configuration error: %s", e)
        if e.fix:
            log.error("    fix: %s", e.fix)
        raise SystemExit(3)
    except PipelineError as e:
        log_exception(log, "pipeline failed", e)
        raise SystemExit(1)
    except Exception as e:
        log_exception(log, "unexpected pipeline error", e)
        raise SystemExit(1)

    log.info("DONE → %s", out_path)
    print(out_path)


if __name__ == "__main__":
    main()
