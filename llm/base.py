"""Abstract LLM provider — the swappability contract for the parse step.

Every provider implements this interface. `pipeline/parse.py` depends on
this module only, never on a concrete provider. Mirrors the `TTSBackend`
ABC pattern (one method that matters + sensible defaults).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class LLMProvider(ABC):
    """Abstract LLM provider."""

    name: str = "abstract"
    default_model: str = ""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        """Single-turn completion. Returns the model's text response.

        Implementations:
          - MUST respect the `system` string as a system prompt (not merged
            into `user`), since the parse prompt lives in prompts/parse_story.md
            and is long / load-bearing.
          - SHOULD read API credentials from env vars; api_key kwarg may
            override for tests.
          - MUST raise a clear exception on auth / quota / network failure
            (the orchestrator catches and surfaces to the user).
        """
