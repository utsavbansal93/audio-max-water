"""Launcher for Phase 2 surfaces: web UI and/or MCP server.

Usage:
    python -m pipeline.serve                   # default: web UI on :8765
    python -m pipeline.serve --mode ui         # explicit
    python -m pipeline.serve --mode mcp        # MCP server over stdio (for Claude Code)
    python -m pipeline.serve --port 9000       # override port
    python -m pipeline.serve --host 0.0.0.0    # expose on LAN (default: localhost only)

The web UI serves the five-screen Apple-flavored flow; the MCP server
exposes pipeline tools for Claude Code / Claude Desktop integration.

The two modes currently run in separate processes. A future enhancement
will merge them into one process so the UI's "Use my Claude app"
option can drive LLM calls via MCP sampling.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]


def run_ui(host: str, port: int, reload: bool) -> None:
    """Boot the FastAPI app with uvicorn."""
    # Load .env early so API keys are available to the settings service.
    from pipeline._env import load_default_env
    load_default_env()

    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="uvicorn",
            feature="Web UI",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e

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
    ap.add_argument("--mode", default="ui", choices=["ui", "mcp"],
                    help="Which surface to start. Default: ui.")
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
        elif args.mode == "mcp":
            run_mcp()
    except KeyboardInterrupt:
        print("\n  stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
