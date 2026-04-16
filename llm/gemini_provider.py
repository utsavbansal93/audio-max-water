"""Gemini provider for the parse step.

Uses the `google-genai` SDK. Reads `GEMINI_API_KEY` from env unless an
explicit `api_key` is passed. Default model `gemini-2.5-pro` — faithful
wording matters more than speed for this step.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"
    # flash-lite-preview is reachable on the free tier; 2.5-pro is rate-
    # limited to 0 there. Override with --model for paid tiers where
    # you want gemini-3.1-pro-preview or similar.
    default_model = "gemini-3.1-flash-lite-preview"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="google-genai",
                feature="Gemini LLM provider (parse step)",
                install=".venv/bin/pip install -e '.[llm-gemini]'",
                required=True,
            ) from e
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            from pipeline._errors import ConfigurationError
            raise ConfigurationError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) not set.",
                fix="export GEMINI_API_KEY=<your key>  "
                    "(or pass --provider anthropic with ANTHROPIC_API_KEY)",
            )
        self._client = genai.Client(api_key=key)
        self._model = model or self.default_model

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        from google.genai import types  # type: ignore[import-not-found]

        resp = self._client.models.generate_content(
            model=model or self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""
