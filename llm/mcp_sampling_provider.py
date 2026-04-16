"""LLMProvider that delegates to an MCP client via sampling/createMessage.

The idea: when the web UI and an MCP server run in the same process,
and a Claude client is connected, the parse step can ask the connected
Claude to generate the script — no API key required.

Status: **stub**. Sampling requires the current process to have an
active MCP server `RequestContext` with a connected client. In Phase 2
MVP the UI and MCP server are separate invocations (web UI = HTTP /
uvicorn; MCP = stdio / spawned by Claude), so there is no shared
context. Selecting this provider in the UI will raise a
`ConfigurationError` with setup instructions until the
combined-mode launcher lands.

When implemented, the flow is:
  1. `pipeline/serve.py --mode both` starts FastAPI + an MCP server
     that exposes sampling capability + the pipeline tools.
  2. User configures Claude Code to connect to the MCP server.
  3. In the UI, user selects "Use my Claude app" as provider.
  4. Parse worker calls this provider, which uses
     `server.request_context.session.create_message(...)` to ask
     the connected client for a completion.

Until then, using this provider raises a clear ConfigurationError
telling the user to switch to Anthropic or Gemini.
"""
from __future__ import annotations

import logging
from typing import Optional

from pipeline._errors import ConfigurationError

from .base import LLMProvider


log = logging.getLogger(__name__)


class MCPSamplingProvider(LLMProvider):
    """Placeholder provider. Raises on init until the combined-mode
    launcher lands (see module docstring)."""

    name = "mcp"
    default_model = ""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,  # unused; signature mirrors the others
        model: Optional[str] = None,
    ) -> None:
        raise ConfigurationError(
            "MCP sampling provider is not yet wired up.",
            fix=(
                "Switch your UI settings to 'Anthropic' or 'Google Gemini' "
                "with a saved API key. MCP sampling needs the UI and the "
                "MCP server to run in one process (combined mode), which "
                "is planned but not yet implemented. In the meantime, you "
                "can drive the pipeline from Claude Code directly by "
                "running `python -m pipeline.serve --mode mcp` and adding "
                "it as an MCP server in your Claude config."
            ),
        )

    def complete(self, system: str, user: str, *, model: Optional[str] = None, max_tokens: int = 16000) -> str:  # pragma: no cover
        raise ConfigurationError(
            "MCP sampling provider not implemented yet.",
            fix="See llm/mcp_sampling_provider.py docstring.",
        )
