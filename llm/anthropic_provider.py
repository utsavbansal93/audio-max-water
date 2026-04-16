"""Anthropic provider for the parse step.

Uses the official `anthropic` SDK. Reads `ANTHROPIC_API_KEY` from env
unless an explicit `api_key` is passed. Default model `claude-opus-4-5`,
which is the right default for careful faithful-wording parsing of prose.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = "claude-opus-4-5"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="anthropic",
                feature="Anthropic LLM provider (parse step)",
                install=".venv/bin/pip install -e '.[llm]'",
                required=True,
            ) from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            from pipeline._errors import ConfigurationError
            raise ConfigurationError(
                "ANTHROPIC_API_KEY not set.",
                fix="export ANTHROPIC_API_KEY=<your key>  "
                    "(or pass --provider gemini with GEMINI_API_KEY)",
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or self.default_model

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        resp = self._client.messages.create(
            model=model or self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # messages.create returns TextBlock[]; concatenate any text blocks.
        parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)
