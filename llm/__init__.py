"""LLM provider factory for the parse step.

Pipeline code uses: `llm.get_provider(name)` — never imports a concrete
provider. Adding a provider = one file + one line here. Mirrors the
`tts.get_backend` pattern so both abstractions feel the same to maintain.

Providers are used only by `pipeline/parse.py` for raw-text → script.json
conversion. The render/qa/package stages are LLM-free.
"""
from __future__ import annotations

from typing import Any

from .base import LLMProvider


def get_provider(name: str, **kwargs: Any) -> LLMProvider:
    name = name.lower().strip()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(**kwargs)
    if name in ("gemini", "google", "google-gemini"):
        from .gemini_provider import GeminiProvider
        return GeminiProvider(**kwargs)
    if name == "mcp":
        from .mcp_sampling_provider import MCPSamplingProvider
        return MCPSamplingProvider(**kwargs)
    raise ValueError(f"Unknown LLM provider: {name!r}. Known: anthropic, gemini, mcp")


__all__ = ["LLMProvider", "get_provider"]
