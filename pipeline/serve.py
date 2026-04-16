"""Launcher for Phase 2 surfaces: web UI, MCP server, or combined.

Usage:
    python -m pipeline.serve                     # default: web UI on :8765
    python -m pipeline.serve --mode ui           # web UI alone
    python -m pipeline.serve --mode mcp          # MCP server over stdio (Claude spawns)
    python -m pipeline.serve --mode combined     # web UI + MCP over HTTP/SSE in one process
    python -m pipeline.serve --port 9000         # override port
    python -m pipeline.serve --host 0.0.0.0      # expose on LAN

The three modes serve different workflows:
  - `ui`:       non-Claude users with their own Anthropic/Gemini API key.
  - `mcp`:      Claude Code / Desktop spawning the server as a subprocess
                (stdio) to invoke pipeline tools on demand.
  - `combined`: UI + HTTP-mode MCP server in the same process. The UI's
                "Use my Claude app" provider option (Settings → provider
                = mcp) routes the parse-step LLM call through the
                connected Claude client via sampling/createMessage.
                No API key needed.

For combined mode the user configures Claude Code to connect over HTTP:
    ~/.claude/settings.json
    {
      "mcpServers": {
        "audio-max-water": {"url": "http://localhost:8765/mcp/sse"}
      }
    }
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]


def _require_uvicorn():
    try:
        import uvicorn  # type: ignore[import-not-found]
        return uvicorn
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="uvicorn",
            feature="Web UI",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e


def run_ui(host: str, port: int, reload: bool) -> None:
    """Boot the FastAPI app with uvicorn — web UI only, no MCP mount."""
    from pipeline._env import load_default_env
    load_default_env()

    uvicorn = _require_uvicorn()
    url = f"http://{host}:{port}"
    print(f"\n  Audio Max Water\n  → open {url}\n")
    uvicorn.run(
        "ui.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        access_log=False,
    )


def run_combined(host: str, port: int, reload: bool) -> None:
    """Boot the FastAPI app with uvicorn + mount the MCP server on
    /mcp/sse. The UI's 'Use my Claude app' provider becomes usable."""
    from pipeline._env import load_default_env
    load_default_env()

    # Tell the app to call `ui.mcp_mount.attach(app)` from its lifespan.
    # We use an env var because uvicorn imports the app lazily and we
    # can't pass constructor kwargs through the `"ui.app:app"` path.
    os.environ["AMW_MCP_COMBINED"] = "1"

    uvicorn = _require_uvicorn()
    url = f"http://{host}:{port}"
    print(f"\n  Audio Max Water (combined: UI + MCP/SSE)")
    print(f"  → open     {url}")
    print(f"  → MCP URL  {url}/mcp/sse")
    print(f"\n  Configure Claude Code:")
    print(f"    ~/.claude/settings.json")
    print(f'    {{"mcpServers": {{"audio-max-water": {{"url": "{url}/mcp/sse"}}}}}}\n')
    uvicorn.run(
        "ui.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        access_log=False,
    )


def run_mcp() -> None:
    """Run the MCP server over stdio (for Claude Code / Claude Desktop)."""
    try:
        from pipeline.mcp_server import run_stdio
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="mcp",
            feature="MCP server",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e
    run_stdio()


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="pipeline.serve",
        description="Run the Audio Max Water web UI and/or MCP server.",
    )
    ap.add_argument("--mode", default="ui",
                    choices=["ui", "mcp", "combined"],
                    help="Which surface to start. Default: ui. "
                         "'combined' runs UI + MCP over HTTP/SSE in one process.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind address for the web UI. Default: 127.0.0.1 "
                         "(localhost only). Use 0.0.0.0 to expose on LAN.")
    ap.add_argument("--port", type=int, default=8765,
                    help="Port for the web UI. Default: 8765.")
    ap.add_argument("--reload", action="store_true",
                    help="Enable uvicorn auto-reload (development).")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)-20s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        if args.mode == "ui":
            run_ui(host=args.host, port=args.port, reload=args.reload)
        elif args.mode == "combined":
            run_combined(host=args.host, port=args.port, reload=args.reload)
        elif args.mode == "mcp":
            run_mcp()
    except KeyboardInterrupt:
        print("\n  stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
