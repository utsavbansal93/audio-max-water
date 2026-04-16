"""Minimal .env loader — no python-dotenv dependency.

Loads `KEY=VALUE` pairs from `.env` at the repo root into `os.environ`
at orchestrator startup. Existing env vars take precedence, so an
explicit `export ANTHROPIC_API_KEY=...` in the shell still overrides
whatever's in `.env`.

Scope is intentionally tight: no multi-line values, no interpolation,
no shell expansion. Comments (`#`) and blank lines are skipped.
Surrounding quotes on values are stripped.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path


log = logging.getLogger(__name__)


def load_env_file(path: Path) -> int:
    """Read KEY=VALUE pairs from `path` into `os.environ`. Skip keys
    that are already set. Returns the number of keys added."""
    if not path.exists():
        return 0

    # Warn loudly on insecure perms — .env holds API keys.
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            log.warning(
                ".env has permissions %o (world/group-readable). "
                "Recommended: chmod 600 %s", mode, path,
            )
    except OSError:
        pass

    added = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Do not overwrite explicit env from the shell.
        if key in os.environ:
            continue
        if key:
            os.environ[key] = value
            added += 1
    return added


def load_default_env() -> int:
    """Load the repo-root `.env` (the canonical location). Safe no-op
    when the file isn't present."""
    repo = Path(__file__).resolve().parents[1]
    return load_env_file(repo / ".env")
