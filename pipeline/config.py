"""Per-story config loading with deep-merge override support.

Usage:
    from pipeline.config import load_config
    cfg = load_config(build_dir)   # loads config.yaml + <build_dir>/config.yaml

Any key in <build_dir>/config.yaml overrides the corresponding global default.
Nested dicts are merged recursively, so a story can override a single nested
value (e.g. output.scene_pause_ms) without having to repeat the whole block.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base in-place. Returns base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(build_dir: Path | None = None) -> dict:
    """Load base config.yaml, deep-merging <build_dir>/config.yaml on top if present."""
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    if build_dir is not None:
        story_cfg = Path(build_dir) / "config.yaml"
        if story_cfg.exists():
            _deep_merge(cfg, yaml.safe_load(story_cfg.read_text()))
    return cfg
