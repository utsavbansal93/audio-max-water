"""LLMProvider that delegates to a connected Claude client via MCP sampling.

When `python -m pipeline.serve --mode combined` is running and a Claude
client (Claude Code / Desktop) is connected to the embedded MCP server
over HTTP/SSE, the parse step's LLM call is routed through the
client's `sampling/createMessage` handler. The user never needs an
Anthropic/Gemini API key — their connected Claude client does the
work.

Flow:
  1. User runs `pipeline.serve --mode combined`.
  2. User configures Claude Code to connect:
       ~/.claude/settings.json
       {
         "mcpServers": {
           "audio-max-water": {"url": "http://localhost:8765/mcp/sse"}
         }
       }
  3. User selects "Use my Claude app" as provider in Settings.
  4. Parse worker calls `complete()` here; we bridge the async
     `session.create_message()` from the worker thread onto the
     uvicorn event loop with `asyncio.run_coroutine_threadsafe`.

Hard-fail policy (per user decision):
  - If no Claude client is currently connected, raise
    `ConfigurationError` with the exact fix instructions. No silent
    fallback to Anthropic/Gemini.
  - If the client disconnects mid-call, raise `ConfigurationError`
    with "client disconnected — try again or switch provider".
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pipeline._errors import ConfigurationError

from .base import LLMProvider


log = logging.getLogger(__name__)


# Parse-step ceiling. Claude Code's underlying model can take a while
# for long books; 180s matches our tolerance. The session's own
# internal timeout is longer than this by default.
_SAMPLING_TIMEOUT_S = 180.0


class MCPSamplingProvider(LLMProvider):
    """Route LLM completions through a connected Claude client via MCP."""

    name = "mcp"
    default_model = ""  # the client picks its own model; we send a preference hint

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,  # unused — signature mirrors other providers
        model: Optional[str] = None,
    ) -> None:
        # No init work. Session is looked up at complete() time so
        # disconnects between __init__ and complete are handled.
        self._model_hint = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        from ui.mcp_mount import get_current_session, get_current_loop, is_attached

        if not is_attached():
            raise ConfigurationError(
                "MCP sampling isn't available in this process.",
                fix=(
                    "Restart the server with combined mode:\n"
                    "    python -m pipeline.serve --mode combined\n"
                    "Then configure Claude Code to connect: add\n"
                    '    "audio-max-water": {"url": "http://localhost:8765/mcp/sse"}\n'
                    "to the `mcpServers` block in ~/.claude/settings.json."
                ),
            )

        session = get_current_session()
        loop = get_current_loop()
        if session is None or loop is None:
            raise ConfigurationError(
                "Your Claude app isn't connected over MCP right now.",
                fix=(
                    "Start Claude Code with audio-max-water as an MCP server:\n"
                    '    "audio-max-water": {"url": "http://localhost:8765/mcp/sse"}\n'
                    "in ~/.claude/settings.json. Or switch the provider to "
                    "Anthropic / Google Gemini in Settings."
                ),
            )

        try:
            from mcp.types import SamplingMessage, TextContent  # type: ignore[import-not-found]
            from mcp.shared.exceptions import McpError  # type: ignore[import-not-found]
        except ImportError as e:
            from pipeline._errors import MissingDependency
            raise MissingDependency(
                package="mcp",
                feature="MCP sampling provider",
                install=".venv/bin/pip install -e '.[ui]'",
                required=True,
            ) from e

        chosen_model = model or self._model_hint or None

        # Build the sampling request. MCP's SamplingMessage format is
        # role + single content block; we wrap the user text as a text
        # content. The system prompt is passed separately.
        request_messages = [
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=user),
            )
        ]

        log.info("mcp sampling: requesting %d-token completion from connected client",
                 max_tokens)

        async def _do_request():
            return await session.create_message(
                messages=request_messages,
                system_prompt=system,
                max_tokens=max_tokens,
                # model_preferences is a soft hint — the client picks.
                # Claude Code ignores it in 2026; still the right place.
            )

        future = asyncio.run_coroutine_threadsafe(_do_request(), loop)
        try:
            result = future.result(timeout=_SAMPLING_TIMEOUT_S)
        except TimeoutError as e:
            raise ConfigurationError(
                f"MCP sampling timed out after {_SAMPLING_TIMEOUT_S:.0f}s.",
                fix=(
                    "The connected Claude client didn't respond in time. "
                    "Try again, or switch provider to Anthropic / Google Gemini."
                ),
            ) from e
        except McpError as e:
            raise ConfigurationError(
                f"MCP sampling failed: {e.error.message if hasattr(e, 'error') else e}",
                fix=(
                    "Your Claude client may have disconnected or doesn't "
                    "support sampling. Try reconnecting, or switch to "
                    "Anthropic / Google Gemini in Settings."
                ),
            ) from e
        except Exception as e:
            # Cancellation, stream-closed, etc.
            raise ConfigurationError(
                f"MCP sampling error: {type(e).__name__}: {e}",
                fix=(
                    "Your Claude client may have disconnected. Try again, "
                    "or switch to Anthropic / Google Gemini in Settings."
                ),
            ) from e

        # Extract the text from the result. CreateMessageResult has a
        # `content` field that's a single content block (text, image, etc.)
        # or a list depending on SDK version. Handle both.
        parts: list[str] = []
        content = getattr(result, "content", None)
        if content is None:
            raise ConfigurationError(
                "MCP sampling returned no content.",
                fix="Try again, or switch provider.",
            )
        if isinstance(content, list):
            blocks = content
        else:
            blocks = [content]
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if not parts:
            raise ConfigurationError(
                "MCP sampling returned no text content.",
                fix="The client may have returned non-text blocks. Try again.",
            )
        joined = "".join(parts)
        log.info("mcp sampling: got %d chars from client (model=%r)",
                 len(joined), getattr(result, "model", "?"))
        return joined
