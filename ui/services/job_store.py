"""Persistent job history — survives server restarts.

Each job gets a JSON record at `<jobs_root>/<job_id>.json`. Active jobs
are also kept in memory by SessionManager; the store is the source of
truth for everything else (history page, resume, cleanup).

Resume semantics:
  - On server startup, scan `<jobs_root>/*.json` and load all records.
  - A job with `status=error` gets a "Resume" button in the UI.
  - The resume path walks the build_dir and skips stages whose artifacts
    already exist (source.md, script.json, cast.json, chapter MP3s).
    Existing stage caches in the pipeline (content-hash WAVs, etc.) do
    the heavy lifting — this module just decides where to restart.

The JSON shape is intentionally flat + conservative: strings, ints,
nested dicts, no custom Pydantic model. That way we can evolve the
Job dataclass without breaking old job files.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


log = logging.getLogger(__name__)


REPO = Path(__file__).resolve().parents[2]
JOBS_ROOT = REPO / "build" / "_jobs"


StageKey = str  # "ingest" | "parse" | "cast" | "render" | "qa" | "package"
StageStatus = str  # "pending" | "active" | "done" | "error" | "skipped"


ORDERED_STAGES: tuple[StageKey, ...] = (
    "ingest", "parse", "cast", "render", "package",
)


@dataclass
class StageState:
    key: StageKey
    status: StageStatus = "pending"
    message: str = ""
    current: int = 0
    total: int = 0
    started_at: Optional[float] = None      # unix seconds
    ended_at: Optional[float] = None
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def ratio(self) -> float:
        return (self.current / self.total) if self.total > 0 else 0.0

    def duration_s(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.ended_at or time.time()
        return end - self.started_at


@dataclass
class PersistedJob:
    """Everything we persist about a job. Subset of ui.services.session.Job
    so the in-memory richer state (asyncio.Queue, threads) stays runtime-only.
    """
    job_id: str
    status: str = "idle"            # overall job status
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    input_path: Optional[str] = None
    input_filename: Optional[str] = None
    build_dir: Optional[str] = None

    title: Optional[str] = None
    n_chapters: int = 0
    n_lines: int = 0

    output_format: str = "m4b"
    backend: str = "mlx-kokoro"
    narrator_backend: str = ""      # "" = fall back to `backend`
    character_backend: str = ""     # "" = fall back to `backend`
    provider: str = "anthropic"
    cover_path: Optional[str] = None

    output_path: Optional[str] = None
    error: Optional[str] = None

    stages: dict[StageKey, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_path": self.input_path,
            "input_filename": self.input_filename,
            "build_dir": self.build_dir,
            "title": self.title,
            "n_chapters": self.n_chapters,
            "n_lines": self.n_lines,
            "output_format": self.output_format,
            "backend": self.backend,
            "narrator_backend": self.narrator_backend,
            "character_backend": self.character_backend,
            "provider": self.provider,
            "cover_path": self.cover_path,
            "output_path": self.output_path,
            "error": self.error,
            "stages": self.stages,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PersistedJob":
        # Ignore unknown keys so older on-disk records still load.
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        # Fill defaults for new fields not in the old record.
        return cls(**clean)

    def stage(self, key: StageKey) -> StageState:
        raw = self.stages.get(key)
        if raw is None:
            s = StageState(key=key)
        else:
            s = StageState(**raw)
        return s

    def set_stage(self, state: StageState) -> None:
        self.stages[state.key] = state.to_dict()
        self.updated_at = time.time()

    def public_view(self) -> dict:
        """JSON-safe snapshot for templates + JSON API."""
        stages = [self.stage(k).to_dict() for k in ORDERED_STAGES]
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_filename": self.input_filename,
            "build_dir": self.build_dir,
            "title": self.title,
            "n_chapters": self.n_chapters,
            "n_lines": self.n_lines,
            "output_format": self.output_format,
            "backend": self.backend,
            "narrator_backend": self.narrator_backend or self.backend,
            "character_backend": self.character_backend or self.backend,
            "provider": self.provider,
            "cover_filename": Path(self.cover_path).name if self.cover_path else None,
            "output_path": self.output_path,
            "error": self.error,
            "stages": stages,
            "resumable": self.status == "error",
            "has_output": self.output_path is not None and Path(self.output_path).exists(),
        }


class JobStore:
    """Reads + writes PersistedJob records to disk."""

    def __init__(self, root: Path = JOBS_ROOT) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def save(self, job: PersistedJob) -> None:
        job.updated_at = time.time()
        path = self.path_for(job.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)
        log.debug("job saved: %s (status=%s)", job.job_id, job.status)

    def load(self, job_id: str) -> Optional[PersistedJob]:
        path = self.path_for(job_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PersistedJob.from_dict(data)
        except Exception as e:
            log.warning("failed to load job %s: %s", job_id, e)
            return None

    def all(self) -> list[PersistedJob]:
        """Return all jobs, newest first."""
        jobs: list[PersistedJob] = []
        for p in self.root.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                jobs.append(PersistedJob.from_dict(data))
            except Exception as e:
                log.warning("skipping malformed job file %s: %s", p, e)
        jobs.sort(key=lambda j: j.updated_at, reverse=True)
        return jobs

    def delete(self, job_id: str, *, remove_build: bool = False) -> bool:
        """Remove the job record. Optionally remove the build directory too."""
        job = self.load(job_id)
        path = self.path_for(job_id)
        if path.exists():
            path.unlink()
        if remove_build and job and job.build_dir:
            import shutil
            bd = Path(job.build_dir)
            if bd.exists() and bd.is_dir():
                shutil.rmtree(bd, ignore_errors=True)
        return True


def detect_last_good_stage(build_dir: Path) -> str:
    """Walk the build directory and report the deepest stage whose
    artifacts are fully present. Returned stage name is the one the
    caller should START from when resuming (the *first* stage without
    a full artifact)."""
    bd = Path(build_dir)
    source_md = bd / "source.md"
    script_json = bd / "script.json"
    cast_json = bd / "cast.json"

    if not source_md.exists():
        return "ingest"
    if not script_json.exists():
        return "parse"
    if not cast_json.exists():
        return "cast"
    # Check chapter MP3s exist. If even one is missing, resume render.
    try:
        script = json.loads(script_json.read_text(encoding="utf-8"))
    except Exception:
        return "parse"
    for ch in script.get("chapters", []):
        mp3 = bd / f"ch{ch['number']:02d}" / f"chapter_{ch['number']:02d}.mp3"
        if not mp3.exists():
            return "render"
    return "package"
