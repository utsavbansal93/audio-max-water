"""Persisted user settings — API keys, default provider, default format.

Lives at `~/.config/audio-max-water/settings.toml` (0600 perms). Loaded
at app startup; injected into `os.environ` so the existing LLMProvider
code reads them without any UI-specific wiring.

Env vars ALWAYS win over the settings file — an explicit
`ANTHROPIC_API_KEY=xxx python -m pipeline.serve` overrides whatever's
saved.
"""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


log = logging.getLogger(__name__)


Provider = Literal["anthropic", "gemini", "mcp"]

CONFIG_DIR = Path.home() / ".config" / "audio-max-water"
SETTINGS_PATH = CONFIG_DIR / "settings.toml"


@dataclass
class Settings:
    # LLM provider choice + credentials
    provider: Provider = "anthropic"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_model: str = ""   # empty string = provider default
    gemini_model: str = ""

    # Render defaults
    backend: str = "mlx-kokoro"
    output_format: Literal["m4b", "epub3"] = "m4b"

    # UI
    theme: Literal["system", "light", "dark"] = "system"

    def apply_to_env(self) -> None:
        """Inject credentials into os.environ without clobbering existing."""
        if self.anthropic_api_key and "ANTHROPIC_API_KEY" not in os.environ:
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.gemini_api_key and "GEMINI_API_KEY" not in os.environ:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key

    def has_key_for(self, provider: str) -> bool:
        """True iff we have credentials (env or stored) for `provider`."""
        if provider == "anthropic":
            return bool(self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
        if provider == "gemini":
            return bool(
                self.gemini_api_key
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
            )
        if provider == "mcp":
            return True  # sampling works if an MCP client is connected
        return False

    def public_view(self) -> dict:
        """Dict for sending to the UI. Keys are redacted except for length
        hint so users know something's saved."""
        def redact(s: str) -> str:
            if not s:
                return ""
            return f"•••• {len(s)} chars"
        return {
            "provider": self.provider,
            "anthropic_api_key": redact(self.anthropic_api_key),
            "gemini_api_key": redact(self.gemini_api_key),
            "anthropic_model": self.anthropic_model,
            "gemini_model": self.gemini_model,
            "backend": self.backend,
            "output_format": self.output_format,
            "theme": self.theme,
            "env_has_anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "env_has_gemini": bool(
                os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            ),
        }


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    if not path.exists():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("failed to parse %s: %s — using defaults", path, e)
        return Settings()
    # Flatten [llm] / [output] / [ui] if present; accept flat shape too.
    flat: dict = {}
    if isinstance(data, dict):
        for section, value in data.items():
            if isinstance(value, dict):
                flat.update(value)
            else:
                flat[section] = value
    # Drop unknown keys so we don't trip dataclass init.
    known = {f for f in Settings.__dataclass_fields__}
    clean = {k: v for k, v in flat.items() if k in known}
    try:
        return Settings(**clean)
    except TypeError as e:
        log.warning("settings schema mismatch (%s) — using defaults", e)
        return Settings()


def save_settings(settings: Settings, path: Path = SETTINGS_PATH) -> None:
    """Write settings to disk with 0600 perms. Creates parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal TOML writer — no external dep. Strings are escaped with repr()-
    # like behavior: we wrap in double-quotes and escape backslashes / quotes.
    d = asdict(settings)

    def toml_str(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines: list[str] = ["# Saved by audio-max-water UI", ""]
    lines.append("[llm]")
    lines.append(f"provider = {toml_str(d['provider'])}")
    lines.append(f"anthropic_api_key = {toml_str(d['anthropic_api_key'])}")
    lines.append(f"gemini_api_key = {toml_str(d['gemini_api_key'])}")
    lines.append(f"anthropic_model = {toml_str(d['anthropic_model'])}")
    lines.append(f"gemini_model = {toml_str(d['gemini_model'])}")
    lines.append("")
    lines.append("[output]")
    lines.append(f"backend = {toml_str(d['backend'])}")
    lines.append(f"output_format = {toml_str(d['output_format'])}")
    lines.append("")
    lines.append("[ui]")
    lines.append(f"theme = {toml_str(d['theme'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError as e:
        log.warning("chmod 0600 failed on %s: %s", path, e)
    log.info("saved settings to %s", path)
