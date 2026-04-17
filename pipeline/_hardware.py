"""Hardware probe written at render start and end.

A lightweight read-only snapshot of the machine's state, recorded to
`build/<stem>/hardware_{start,end}.json`. Purpose: historical data so future
runs can reason about thermal-throttle / memory-pressure / MPS-availability
patterns without rerunning diagnostic shells by hand.

Never raises on probe failure — the render must proceed even if a subsystem
(like `pmset` not on PATH in a minimal environment) is unavailable. Fields
are optional; consumers should guard on dict.get().

See BACKLOG "Optimal hardware resource usage — a strategy, not just a policy"
for the larger system this feeds.
"""
from __future__ import annotations

import json
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


def probe_hardware() -> dict[str, Any]:
    """Read-only snapshot. All fields wrapped so failure of any one probe
    does not kill the whole snapshot."""
    d: dict[str, Any] = {
        "timestamp": time.time(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }

    # CPU / RAM via psutil (already a transitive dep of the project).
    try:
        import psutil
        d["cpu_count_logical"] = psutil.cpu_count(logical=True)
        d["cpu_count_physical"] = psutil.cpu_count(logical=False)
        vm = psutil.virtual_memory()
        d["ram_total_gb"] = round(vm.total / 1024**3, 2)
        d["ram_available_gb"] = round(vm.available / 1024**3, 2)
        d["ram_percent_used"] = vm.percent
    except Exception as e:
        d["_psutil_error"] = str(e)

    # macOS thermal state — pmset records emergency events, not gradual
    # downclock, but even the "no warnings" output is historically useful.
    try:
        out = subprocess.run(
            ["pmset", "-g", "therm"], capture_output=True, text=True, timeout=2,
        )
        d["thermal_raw"] = out.stdout.strip()
    except Exception as e:
        d["thermal_raw"] = f"unavailable: {e}"

    # Apple Silicon perf / efficiency core split
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.perflevel0.logicalcpu", "hw.perflevel1.logicalcpu"],
            capture_output=True, text=True, timeout=2,
        )
        parts = [p for p in out.stdout.strip().splitlines() if p]
        if len(parts) >= 2:
            d["cpu_perf_cores"] = int(parts[0])
            d["cpu_efficiency_cores"] = int(parts[1])
    except Exception:
        pass

    # PyTorch MPS availability — handy to have in the record; may force torch
    # import which is already loaded in a render context so free there.
    try:
        import torch  # type: ignore
        d["mps_available"] = bool(torch.backends.mps.is_available())
    except Exception as e:
        d["mps_available"] = None
        d["_torch_error"] = str(e)

    return d


def write_hardware_snapshot(build_dir, phase: str, extras: dict | None = None) -> Path:
    """Write probe_hardware() plus caller-supplied `extras` (e.g. peak_rss_mb,
    wall_clock_s for the end-phase snapshot) to a JSON file in build_dir.
    Never raises — on failure, returns a Path that may not exist."""
    build_dir = Path(build_dir)
    path = build_dir / f"hardware_{phase}.json"
    try:
        d = probe_hardware()
        if extras:
            d.update(extras)
        build_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, indent=2) + "\n")
        log.info("hardware snapshot (%s) written to %s", phase, path)
    except Exception as e:
        log.warning("hardware snapshot (%s) failed: %s", phase, e)
    return path
