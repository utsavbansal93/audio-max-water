"""Mount an MCP server onto the FastAPI app as HTTP/SSE endpoints.

This is what makes combined mode work. The web UI and the MCP server
run in the same uvicorn process; when Claude Code connects via SSE we
capture the live `ServerSession` into a module-global. The
`MCPSamplingProvider` in `llm/mcp_sampling_provider.py` reaches the
session through `get_current_session()` so parse-step LLM calls can
go through Claude.

Session lifecycle:
  - Captured on `/mcp/sse` GET (when Claude connects).
  - Cleared when the SSE stream closes (Claude disconnects or server stops).
  - Access is guarded by a lock; reads are cheap.

Event-loop bridge:
  The parse worker runs on a background thread (see `ui/app.py::_start_parse`).
  `ServerSession.create_message` is async and lives on uvicorn's asyncio
  loop. `get_current_loop()` returns the captured event loop so the
  sampling provider can use `asyncio.run_coroutine_threadsafe` to bridge
  the thread boundary.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import Response


log = logging.getLogger(__name__)


# Module-globals guarded by a lock. Reads are fast; writes are rare
# (only on connect / disconnect).
_lock = threading.Lock()
_current_session = None  # ServerSession | None
_current_loop: Optional[asyncio.AbstractEventLoop] = None
_attached = False


def get_current_session():
    """Return the live MCP ServerSession, or None if no client connected."""
    with _lock:
        return _current_session


def get_current_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the asyncio event loop the MCP session is running on.

    Used by `llm/mcp_sampling_provider.py` to schedule the async
    `create_message` call from the parse worker thread.
    """
    return _current_loop


def is_attached() -> bool:
    """True iff `attach(app)` was called (combined mode)."""
    return _attached


def attach(app: FastAPI) -> None:
    """Mount MCP SSE routes onto the given FastAPI app.

    Called from `pipeline.serve --mode combined` before uvicorn starts.
    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _attached
    if _attached:
        return

    try:
        from mcp.server.sse import SseServerTransport  # type: ignore[import-not-found]
        from mcp.server.session import ServerSession  # type: ignore[import-not-found]
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="mcp",
            feature="MCP HTTP/SSE mount",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e

    from pipeline.mcp_server import build_server

    mcp_server = build_server()
    sse = SseServerTransport("/mcp/messages/")

    # FastAPI can mount raw ASGI callables.
    app.mount("/mcp/messages", sse.handle_post_message)

    @app.get("/mcp/sse")
    async def mcp_sse(request: Request):
        # Capture the uvicorn event loop the first time an SSE connection
        # lands. This is the loop the MCP session lives on; the parse
        # worker thread uses it for run_coroutine_threadsafe.
        global _current_loop, _current_session
        with _lock:
            if _current_loop is None:
                _current_loop = asyncio.get_event_loop()

        log.info("MCP SSE: client connecting")
        async with sse.connect_sse(
            request.scope, request.receive, request._send,
        ) as (read_stream, write_stream):
            await _run_with_session_capture(
                mcp_server, read_stream, write_stream, ServerSession,
            )
        log.info("MCP SSE: client disconnected")
        return Response()

    _attached = True
    log.info("MCP SSE mounted at /mcp/sse + /mcp/messages")


async def _run_with_session_capture(mcp_server, read_stream, write_stream, ServerSession):
    """Replicate `Server.run()`'s body but stash the session in
    `_current_session` so outside code can reach it for sampling.

    Mirrors `mcp/server/lowlevel/server.py::Server.run`: enters the
    server's lifespan, creates a ServerSession, spawns message handlers
    in a task group. On exit (transport closed), cancels in-flight
    handlers and clears our global.

    The only divergence from `Server.run` is the module-global capture
    around the `async for` loop.
    """
    from contextlib import AsyncExitStack
    import anyio

    global _current_session
    init_options = mcp_server.create_initialization_options()

    async with AsyncExitStack() as stack:
        lifespan_context = await stack.enter_async_context(
            mcp_server.lifespan(mcp_server)
        )
        session = await stack.enter_async_context(
            ServerSession(read_stream, write_stream, init_options)
        )

        # Capture for outside-the-handler sampling.
        with _lock:
            _current_session = session

        try:
            async with anyio.create_task_group() as tg:
                try:
                    async for message in session.incoming_messages:
                        tg.start_soon(
                            mcp_server._handle_message,
                            message,
                            session,
                            lifespan_context,
                            False,  # raise_exceptions
                        )
                finally:
                    tg.cancel_scope.cancel()
        finally:
            with _lock:
                _current_session = None
