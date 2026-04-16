"""Phase 2 web UI.

`pipeline/serve.py` is the entry point: `python -m pipeline.serve`
launches a local FastAPI app + (optionally) an MCP server.

The UI is deliberately thin — it orchestrates `pipeline/run.py` behind
the scenes; all the actual work lives in `pipeline/` and `llm/`.
"""
