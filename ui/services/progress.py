"""SSE-friendly progress streaming for a Job.

The pipeline stages emit `ProgressEvent` via callback; the callback is
threadsafe-wired into a per-job `asyncio.Queue` read by the SSE endpoint.

This module has no FastAPI dependency — it only knows how to convert
events to SSE-formatted payloads. `ui/routes/events.py` wraps the
generator in a StreamingResponse.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Callable

from pipeline._events import ProgressEvent


log = logging.getLogger(__name__)


def make_threadsafe_callback(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
) -> Callable[[ProgressEvent], None]:
    """Wrap an asyncio.Queue so a worker thread can enqueue safely.

    The pipeline runs render_all on a background thread (model loads
    block the event loop); this helper lets it still emit events to an
    asyncio queue on the main loop.
    """

    def cb(event: ProgressEvent) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            # Loop closed — worker is still running but we don't care any more.
            pass

    return cb


# Terminal events whose arrival should close the stream.
_TERMINAL = {
    ("package", "done"),
    ("error", "error"),
}


async def stream_events(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings until a terminal event arrives.

    Sends a heartbeat comment every 15 s so intermediate proxies (not
    that we expect any on localhost) don't time out.
    """
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15.0)
        except asyncio.TimeoutError:
            yield ": heartbeat\n\n"
            continue

        # Allow None as a sentinel to close the stream from the producer.
        if event is None:
            break

        data = json.dumps(event.to_dict())
        ev_name = f"{event.stage}:{event.phase}"
        yield f"event: {ev_name}\ndata: {data}\n\n"

        if (event.stage, event.phase) in _TERMINAL:
            # Give the client a beat to process the final event before we
            # close the stream.
            yield ": closing\n\n"
            break
