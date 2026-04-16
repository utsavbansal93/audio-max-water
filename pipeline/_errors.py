"""Structured pipeline errors.

`MissingDependency` is the one that matters: raised when a feature
requires an optional package that isn't installed. The orchestrator
and the Phase-2 UI read its fields to show a useful message (and in
the UI, an Install button) rather than a bare stack trace.

Every optional code path that imports an optional dep should raise
`MissingDependency` — not `RuntimeError`, not `ImportError` — so the
callers can distinguish "install this" from "something else broke".
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base class for all pipeline-raised errors. Catch this if you
    want to handle any of our failures uniformly."""


class MissingDependency(PipelineError):
    """A required or optional package is not installed.

    Attributes:
        package:   the import name that failed (e.g. "ebooklib")
        feature:   human-friendly feature name (e.g. "EPUB ingest")
        install:   the exact install command to run to fix it
        required:  True if the pipeline cannot continue; False if the
                   caller can gracefully skip the feature
    """

    def __init__(
        self,
        *,
        package: str,
        feature: str,
        install: str,
        required: bool = True,
    ) -> None:
        self.package = package
        self.feature = feature
        self.install = install
        self.required = required
        msg = (
            f"{feature} needs `{package}` which is not installed. "
            f"Run:\n    {install}"
        )
        super().__init__(msg)


class ConfigurationError(PipelineError):
    """User-side configuration problem (missing env var, unreadable
    config file, bad flag combination). Distinct from MissingDependency
    so the orchestrator can log it as a known-bad config rather than
    an unexpected crash.
    """

    def __init__(self, message: str, *, fix: str | None = None) -> None:
        self.fix = fix
        super().__init__(message)


class ParseError(PipelineError):
    """The LLM-produced script failed validation (even after retry).

    Raised from `pipeline/parse.py`. Most commonly fires when the model
    paraphrased in a way the faithful-wording normalizer can't excuse.
    """


class RenderError(PipelineError):
    """Render-stage failure — wraps ffmpeg / backend exceptions with
    the line / chapter context that caused them."""
