"""MCP server — exposes the audiobook pipeline as tools for Claude Code / Desktop.

Two transports:
  - stdio (`python -m pipeline.serve --mode mcp`): Claude spawns this as a
    subprocess and drives JSON-RPC over stdin/stdout. Native Claude-Code
    + Claude-Desktop pattern for local tool servers.
  - HTTP/SSE, mounted into the FastAPI web UI (`--mode combined`). The UI's
    "Use my Claude app" provider uses the same connected session to route
    parse-step LLM calls via `sampling/createMessage` — see
    `ui/mcp_mount.py` + `llm/mcp_sampling_provider.py`.

`build_server()` is the single source of truth for tool registration;
both transports consume it. Adding / changing a tool = one edit here.

Tools exposed:
  - run_pipeline          : one-shot end-to-end render
  - list_voices           : return voice catalogue for a backend
  - audition_voice        : synthesize a short sample clip
  - parse_only            : ingest + parse, return the ScriptModel JSON
  - supported_formats     : report input / output formats
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


REPO = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """Load .env so API keys are available when Claude Code invokes the server."""
    from pipeline._env import load_default_env
    load_default_env()


def build_server():
    """Construct the MCP Server with all pipeline tools registered.

    Transport-agnostic — callers (stdio entry point, SSE mount) use the
    returned `Server` instance with whatever read/write streams they
    have.
    """
    try:
        from mcp.server import Server  # type: ignore[import-not-found]
        from mcp.types import TextContent, Tool  # type: ignore[import-not-found]
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="mcp",
            feature="MCP server",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e

    server = Server("audio-max-water")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="run_pipeline",
                description=(
                    "Convert a source file (txt / md / docx / epub / pdf) into an "
                    "audiobook. Runs ingest → LLM parse → cast → render → package. "
                    "Returns the path to the output file. The LLM parse step uses "
                    "ANTHROPIC_API_KEY or GEMINI_API_KEY from the environment."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input_path": {
                            "type": "string",
                            "description": "Absolute path to the source file.",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["m4b", "epub3"],
                            "default": "m4b",
                            "description": "Output format. m4b = audiobook; "
                                           "epub3 = ebook with synced audio (SMIL overlays).",
                        },
                        "cover_path": {
                            "type": "string",
                            "description": "Optional path to cover art (JPG/PNG).",
                        },
                        "backend": {
                            "type": "string",
                            "enum": ["mlx-kokoro", "kokoro", "chatterbox", "xtts"],
                            "default": "mlx-kokoro",
                            "description": "TTS backend. Chatterbox needs reference clips.",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["anthropic", "gemini"],
                            "default": "anthropic",
                            "description": "LLM provider for the parse step.",
                        },
                        "model": {
                            "type": "string",
                            "description": "Override provider default model id.",
                        },
                    },
                    "required": ["input_path"],
                },
            ),
            Tool(
                name="parse_only",
                description=(
                    "Ingest a source file and parse it into a structured script "
                    "(speaker / text / emotion per line). Does not render audio. "
                    "Returns the script as JSON."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "enum": ["anthropic", "gemini"],
                            "default": "anthropic",
                        },
                        "model": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            ),
            Tool(
                name="list_voices",
                description="List voices available in a TTS backend.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "backend": {
                            "type": "string",
                            "enum": ["mlx-kokoro", "kokoro", "chatterbox", "xtts"],
                            "default": "mlx-kokoro",
                        },
                    },
                },
            ),
            Tool(
                name="audition_voice",
                description=(
                    "Render a short sample of a voice reading a line of text. "
                    "Returns the path to the cached WAV file. Useful for letting "
                    "Claude help a user decide between voices before casting."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "backend": {"type": "string", "default": "mlx-kokoro"},
                        "voice_id": {"type": "string"},
                        "text": {
                            "type": "string",
                            "description": "Line to speak. Defaults to a neutral phrase.",
                        },
                    },
                    "required": ["voice_id"],
                },
            ),
            Tool(
                name="supported_formats",
                description="Report supported input and output formats.",
                inputSchema={"type": "object"},
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "run_pipeline":
                return await _tool_run_pipeline(arguments)
            if name == "parse_only":
                return await _tool_parse_only(arguments)
            if name == "list_voices":
                return await _tool_list_voices(arguments)
            if name == "audition_voice":
                return await _tool_audition_voice(arguments)
            if name == "supported_formats":
                return _tool_supported_formats()
            return [TextContent(type="text", text=f"Unknown tool: {name!r}")]
        except Exception as e:
            log.exception("tool %s failed", name)
            return [TextContent(
                type="text",
                text=f"Error calling {name}: {type(e).__name__}: {e}",
            )]

    async def _tool_run_pipeline(args: dict) -> list[TextContent]:
        from mcp.types import TextContent  # noqa: F811
        from pipeline.run import run as run_pipeline
        input_path = Path(args["input_path"]).expanduser().resolve()
        if not input_path.exists():
            return [TextContent(type="text", text=f"File not found: {input_path}")]
        build_dir = REPO / "build" / f"_mcp_{input_path.stem}"
        out_dir = REPO / "out"
        result = await asyncio.to_thread(
            run_pipeline,
            input_path=input_path,
            out_dir=out_dir,
            build_dir=build_dir,
            format=args.get("format", "m4b"),
            backend=args.get("backend"),
            provider=args.get("provider"),
            provider_model=args.get("model"),
            cover_path=Path(args["cover_path"]).expanduser() if args.get("cover_path") else None,
            enable_whisper=False,  # stay quiet in MCP mode — faster
            enable_qa=True,
        )
        return [TextContent(
            type="text",
            text=f"Pipeline complete.\n  output: {result}\n  size:   {result.stat().st_size:,} bytes",
        )]

    async def _tool_parse_only(args: dict) -> list[TextContent]:
        import json
        from mcp.types import TextContent  # noqa: F811
        from pipeline.parse import parse_to_disk
        input_path = Path(args["input_path"]).expanduser().resolve()
        if not input_path.exists():
            return [TextContent(type="text", text=f"File not found: {input_path}")]
        build_dir = REPO / "build" / f"_mcp_{input_path.stem}"
        script, script_path, source_path = await asyncio.to_thread(
            parse_to_disk,
            input_path=input_path,
            build_dir=build_dir,
            provider_name=args.get("provider", "anthropic"),
            model=args.get("model"),
        )
        summary = {
            "title": script.title,
            "n_chapters": len(script.chapters),
            "n_lines": sum(len(c.lines) for c in script.chapters),
            "characters": [c.name for c in script.characters],
            "script_path": str(script_path),
            "source_path": str(source_path),
        }
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    async def _tool_list_voices(args: dict) -> list[TextContent]:
        import json
        from mcp.types import TextContent  # noqa: F811
        backend_name = args.get("backend", "mlx-kokoro")
        from tts import get_backend
        b = await asyncio.to_thread(get_backend, backend_name)
        voices = b.list_voices()
        return [TextContent(type="text", text=json.dumps(
            [
                {
                    "id": v.id,
                    "display_name": v.display_name,
                    "gender": v.gender,
                    "age": v.age,
                    "accent": v.accent,
                    "tags": v.tags,
                }
                for v in voices
            ],
            indent=2,
        ))]

    async def _tool_audition_voice(args: dict) -> list[TextContent]:
        from mcp.types import TextContent  # noqa: F811
        from ui.services.audition import audition
        text = args.get("text") or "I think I shall take the long way home today."
        path = await asyncio.to_thread(
            audition, args.get("backend", "mlx-kokoro"), args["voice_id"], text,
        )
        return [TextContent(
            type="text",
            text=f"Audition saved to {path} ({path.stat().st_size:,} bytes WAV).",
        )]

    def _tool_supported_formats() -> list[TextContent]:
        from mcp.types import TextContent  # noqa: F811
        return [TextContent(type="text", text=(
            "Inputs:  .txt, .md, .docx, .epub, .pdf\n"
            "Outputs: .m4b (audiobook), .epub (ebook with synced audio)"
        ))]

    return server


def run_stdio() -> None:
    """Entry point from `pipeline.serve --mode mcp`. Uses stdio transport."""
    try:
        import mcp.server.stdio  # type: ignore[import-not-found]
    except ImportError as e:
        from pipeline._errors import MissingDependency
        raise MissingDependency(
            package="mcp",
            feature="MCP server",
            install=".venv/bin/pip install -e '.[ui]'",
            required=True,
        ) from e

    _load_env()
    server = build_server()

    async def main():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(main())
