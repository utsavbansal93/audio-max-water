"""Session + job management with on-disk persistence.

`Job` now wraps a `PersistedJob` (from `ui.services.job_store`). The
persistable fields (status, paths, per-stage state) live on the
PersistedJob and are mirrored to disk after every transition. Runtime
fields (asyncio.Queue, worker thread, in-memory ScriptModel) stay
in-process only.

SessionManager tracks the current in-memory job and supports:
  - `new_job()` — start a fresh job (persists immediately).
  - `get(job_id)` — return the in-memory job if it's active, else
    rehydrate from disk (without runtime state).
  - `current()` — the active job, if any.
  - `all_persisted()` — every job on disk, newest first (for /history).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pipeline._events import ProgressEvent
from pipeline.schema import CastModel, ScriptModel
from tts.backend import Voice
from ui.services.job_store import (
    ORDERED_STAGES,
    JobStore,
    PersistedJob,
    StageState,
)


log = logging.getLogger(__name__)


@dataclass
class Job:
    """Per-job state. The `persist` field holds everything written to
    disk; the other fields are runtime-only."""

    persist: PersistedJob

    # In-memory artifacts (loaded lazily from disk on resume).
    script: Optional[ScriptModel] = None
    script_path: Optional[Path] = None
    source_path: Optional[Path] = None
    cast: Optional[CastModel] = None
    cast_path: Optional[Path] = None
    proposals: dict[str, list[Voice]] = field(default_factory=dict)

    # Background worker + SSE queue.
    _queue: Optional[asyncio.Queue[ProgressEvent]] = None
    _thread: Optional[threading.Thread] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _store: Optional[JobStore] = None

    # --- property shortcuts ------------------------------------------

    @property
    def job_id(self) -> str:
        return self.persist.job_id

    @property
    def status(self) -> str:
        return self.persist.status

    @status.setter
    def status(self, v: str) -> None:
        self.persist.status = v
        self.save()

    @property
    def error(self) -> Optional[str]:
        return self.persist.error

    @error.setter
    def error(self, v: Optional[str]) -> None:
        self.persist.error = v
        self.save()

    @property
    def backend(self) -> str:
        return self.persist.backend

    @property
    def provider(self) -> str:
        return self.persist.provider

    @property
    def output_format(self) -> str:
        return self.persist.output_format

    @property
    def input_path(self) -> Optional[Path]:
        return Path(self.persist.input_path) if self.persist.input_path else None

    @property
    def input_filename(self) -> Optional[str]:
        return self.persist.input_filename

    @property
    def build_dir(self) -> Optional[Path]:
        return Path(self.persist.build_dir) if self.persist.build_dir else None

    @property
    def cover_path(self) -> Optional[Path]:
        return Path(self.persist.cover_path) if self.persist.cover_path else None

    @property
    def output_path(self) -> Optional[Path]:
        return Path(self.persist.output_path) if self.persist.output_path else None

    # --- persistence -------------------------------------------------

    def save(self) -> None:
        if self._store is not None:
            try:
                self._store.save(self.persist)
            except Exception as e:
                log.warning("failed to persist job %s: %s", self.job_id, e)

    # --- stage tracking ----------------------------------------------

    def mark_stage(
        self,
        key: str,
        status: str,
        *,
        message: str = "",
        current: int = 0,
        total: int = 0,
        error: str = "",
    ) -> None:
        """Update the per-stage state on disk. Called from `apply_event`
        but also usable directly (for 'skipped' on resume)."""
        existing = self.persist.stage(key)
        now = time.time()
        if status == "active" and existing.started_at is None:
            existing.started_at = now
        if status in ("done", "error", "skipped"):
            existing.ended_at = now
        existing.status = status
        if message:
            existing.message = message
        if current > existing.current:
            existing.current = current
        if total and total != existing.total:
            existing.total = total
        if error:
            existing.error = error
        self.persist.set_stage(existing)
        self.save()

    def apply_event(self, event: ProgressEvent) -> None:
        """Translate a ProgressEvent into a stage update."""
        if event.stage == "error":
            self.persist.error = event.message
            self.persist.status = "error"
            self.save()
            return
        if event.stage not in ORDERED_STAGES:
            return
        if event.phase == "start":
            self.mark_stage(event.stage, "active",
                            message=event.message,
                            current=event.current, total=event.total)
        elif event.phase == "progress":
            self.mark_stage(event.stage, "active",
                            message=event.message,
                            current=event.current, total=event.total)
        elif event.phase == "done":
            self.mark_stage(event.stage, "done",
                            message=event.message,
                            current=max(event.current, event.total),
                            total=event.total)
        elif event.phase == "error":
            self.mark_stage(event.stage, "error",
                            message=event.message,
                            error=event.message)

    # --- public view for templates + API -----------------------------

    def public_view(self) -> dict:
        view = self.persist.public_view()
        # Expose the author + language from the parsed script so the UI
        # can render them on Options / Done screens.
        if self.script:
            view["author"] = self.script.author
            view["language"] = self.script.language
        # Mark whether a source-extracted cover is available for this
        # job — the Options page uses this to show a preview.
        view["source_cover_available"] = self._has_source_cover()
        # Enrich with live in-memory data for the voices page (proposals +
        # character voice-id hints come from propose(), which runs only
        # in-process).
        if self.script:
            view["characters"] = [
                {
                    "name": c.name,
                    "gender": c.gender,
                    "age_hint": c.age_hint,
                    "accent": c.accent,
                    "personality": c.personality,
                    "sample_line": c.sample_lines[0] if c.sample_lines else "",
                    "n_lines": sum(
                        1 for ch in self.script.chapters
                        for line in ch.lines if line.speaker == c.name
                    ),
                    "current_voice": (
                        self.cast.mapping.get(c.name) if self.cast else None
                    ),
                    "proposals": [
                        {
                            "id": v.id,
                            "display_name": v.display_name,
                            "gender": v.gender,
                            "age": v.age,
                            "accent": v.accent,
                            "tags": v.tags,
                        }
                        for v in self.proposals.get(c.name, [])[:5]
                    ],
                }
                for c in self.script.characters
            ]
        return view

    def _has_source_cover(self) -> bool:
        bd = self.build_dir
        if bd is None:
            return False
        for ext in ("jpg", "jpeg", "png", "gif", "webp"):
            if (bd / f"source_cover.{ext}").exists():
                return True
        return False

    # --- hydration from disk (resume path) ---------------------------

    def hydrate_artifacts(self) -> None:
        """Populate runtime `script` / `cast` / etc. from disk if present.
        Called when resuming an errored job."""
        import json as _json
        bd = self.build_dir
        if bd is None:
            return
        s = bd / "script.json"
        if s.exists() and self.script is None:
            try:
                self.script = ScriptModel.model_validate(
                    _json.loads(s.read_text(encoding="utf-8"))
                )
                self.script_path = s
                self.persist.title = self.script.title
                self.persist.n_chapters = len(self.script.chapters)
                self.persist.n_lines = sum(len(c.lines) for c in self.script.chapters)
            except Exception as e:
                log.warning("could not rehydrate script.json: %s", e)
        src = bd / "source.md"
        if src.exists():
            self.source_path = src
        c = bd / "cast.json"
        if c.exists() and self.cast is None:
            try:
                self.cast = CastModel.model_validate(
                    _json.loads(c.read_text(encoding="utf-8"))
                )
                self.cast_path = c
            except Exception as e:
                log.warning("could not rehydrate cast.json: %s", e)


class SessionManager:
    """Holds the active Job. Backed by a disk JobStore so jobs survive restarts."""

    def __init__(self, store: Optional[JobStore] = None) -> None:
        self._store = store or JobStore()
        self._active: Optional[Job] = None
        self._lock = threading.Lock()

    @property
    def store(self) -> JobStore:
        return self._store

    def _wrap(self, persist: PersistedJob) -> Job:
        return Job(persist=persist, _store=self._store)

    def new_job(self) -> Job:
        with self._lock:
            old = self._active
            if old and old._thread and old._thread.is_alive():
                log.warning("starting new job while %s is still working; "
                            "prior job will continue but isn't the active one",
                            old.job_id)
            p = PersistedJob(job_id=uuid.uuid4().hex[:12])
            job = self._wrap(p)
            job.save()
            self._active = job
            log.info("new job: %s", job.job_id)
            return job

    def current(self) -> Optional[Job]:
        return self._active

    def set_active(self, job: Job) -> None:
        """Promote a rehydrated job to active (used by resume)."""
        with self._lock:
            self._active = job

    def get(self, job_id: str) -> Optional[Job]:
        """Return the in-memory job if active, else rehydrate from disk."""
        with self._lock:
            if self._active and self._active.job_id == job_id:
                return self._active
        persist = self._store.load(job_id)
        if persist is None:
            return None
        return self._wrap(persist)

    def require(self) -> Job:
        j = self.current()
        if j is None:
            j = self.new_job()
        return j

    def all_persisted(self) -> list[PersistedJob]:
        """Every job on disk, newest first — used by /history."""
        return self._store.all()

    def delete(self, job_id: str, *, remove_build: bool = False) -> bool:
        with self._lock:
            if self._active and self._active.job_id == job_id:
                self._active = None
        return self._store.delete(job_id, remove_build=remove_build)
