"""FastAPI app for the local-first audiobook builder.

Launched via `python -m pipeline.serve`. Serves the five-screen
Apple-flavored flow (Settings → Upload → Voices → Options → Rendering
→ Done) + an SSE endpoint for progress streaming.

Designed for a single user on localhost. No auth, no multi-session
isolation — one job at a time lives in `SessionManager`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline._errors import ConfigurationError, MissingDependency, PipelineError
from pipeline._events import ProgressEvent
from pipeline._logging import configure_logging
from pipeline.parse import parse_to_disk
from pipeline.run import run as run_pipeline
from tts import get_backend
from ui.services.audition import audition
from ui.services.job_store import detect_last_good_stage
from ui.services.progress import make_threadsafe_callback, stream_events
from ui.services.session import Job, SessionManager
from ui.services.settings import Settings, load_settings, save_settings


log = logging.getLogger(__name__)


REPO = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO / "ui" / "templates"
STATIC_DIR = REPO / "ui" / "static"
UPLOAD_DIR = REPO / "build" / "_ui_uploads"


# --- app lifespan ---------------------------------------------------------

session_mgr = SessionManager()
current_settings: Settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global current_settings
    configure_logging(verbose=False)
    current_settings = load_settings()
    current_settings.apply_to_env()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Jobs left in a transient status by a previous server lifecycle
    # (their worker thread died when the server stopped). Mark them
    # "error" + resumable so the user can pick up where they left off.
    # Stage-status fix-up: if a later stage is already "done", then an
    # earlier "active" stage must have completed before the interruption —
    # mark it done. Only the most-downstream active stage is truly
    # interrupted.
    from ui.services.job_store import ORDERED_STAGES as _STAGES
    rescued = 0
    for persisted in session_mgr.all_persisted():
        if persisted.status not in ("parsing", "rendering", "voices"):
            continue
        persisted.status = "error"
        if not persisted.error:
            persisted.error = ("Job was interrupted (server restart / "
                               "closed browser). Click Resume to continue.")
        # Find the most-downstream "active" stage; anything upstream
        # of a completed stage is retroactively done.
        stage_objs = [persisted.stage(k) for k in _STAGES]
        last_done_idx = max(
            (i for i, s in enumerate(stage_objs) if s.status == "done"),
            default=-1,
        )
        active_idx = next(
            (i for i, s in enumerate(stage_objs) if s.status == "active"),
            None,
        )
        for i, s in enumerate(stage_objs):
            if s.status == "active":
                if i < last_done_idx:
                    s.status = "done"  # retroactively
                else:
                    s.status = "error"
                    if not s.error:
                        s.error = "interrupted"
                persisted.set_stage(s)
        session_mgr.store.save(persisted)
        rescued += 1
    if rescued:
        log.info("UI startup: marked %d interrupted job(s) resumable", rescued)

    log.info("UI started — settings loaded, upload dir=%s", UPLOAD_DIR)
    yield
    log.info("UI shutting down")


app = FastAPI(title="Audio Max Water", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# --- helpers --------------------------------------------------------------


def _render(template: str, request: Request, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, template, ctx)


def _save_upload(file: UploadFile) -> Path:
    """Save an UploadFile to UPLOAD_DIR, return the path. Validates
    extension; raises HTTPException on unsupported format."""
    allowed = {".txt", ".md", ".docx", ".epub", ".pdf"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format {ext!r}. Supported: {sorted(allowed)}",
        )
    safe = Path(file.filename or "upload").name
    # Prefix with timestamp so repeated uploads of "book.epub" don't collide.
    stamp = int(time.time())
    dst = UPLOAD_DIR / f"{stamp}_{safe}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dst


def _cover_path_from_upload(job: Job, file: Optional[UploadFile]) -> Optional[Path]:
    if file is None or file.filename is None or file.filename == "":
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(400, f"Cover must be JPG or PNG (got {ext!r})")
    cov_dir = (job.build_dir or UPLOAD_DIR) / "cover"
    cov_dir.mkdir(parents=True, exist_ok=True)
    dst = cov_dir / f"cover{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dst


def _backends_available() -> list[str]:
    """List of backend names that plausibly load on this machine. No
    actual load is performed — just names. The user picks one, and we
    let the load fail loudly downstream if, e.g., chatterbox isn't
    installed."""
    return ["mlx-kokoro", "kokoro", "chatterbox"]


def _make_ui_callback(job: Job, raw_cb):
    """Wrap the threadsafe SSE callback so every event also updates the
    persisted job (stage tracking + error mirroring)."""
    def cb(event: ProgressEvent) -> None:
        try:
            job.apply_event(event)
        except Exception:
            log.exception("apply_event failed")
        raw_cb(event)
    return cb


def _start_parse(job: Job, provider: str, model: str | None,
                 *, skip_to: str | None = None) -> None:
    """Run ingest+parse+cast on a background thread.

    `skip_to` is used for resume: if set to "cast", skip ingest+parse
    and jump straight to cast proposal (script.json already on disk).
    """
    assert job.input_path is not None
    loop = asyncio.get_running_loop()
    if job._queue is None:
        job._queue = asyncio.Queue()
    raw_cb = make_threadsafe_callback(loop, job._queue)
    cb = _make_ui_callback(job, raw_cb)

    def worker():
        try:
            build_dir = job.build_dir or (REPO / "build" / f"_ui_{job.job_id}")
            build_dir.mkdir(parents=True, exist_ok=True)
            job.persist.build_dir = str(build_dir)
            job.save()

            # Memory watchdog before any heavy loads.
            from pipeline._memory import require_free
            require_free(min_gb=3.5, backend=job.backend)

            # --- stage: ingest+parse (may be skipped on resume) -----
            script_path = build_dir / "script.json"
            if skip_to in (None, "ingest", "parse") or not script_path.exists():
                script, script_path, source_path = parse_to_disk(
                    input_path=job.input_path,
                    build_dir=build_dir,
                    provider_name=provider,
                    model=model,
                    on_progress=cb,
                )
                cb(ProgressEvent(stage="parse", phase="done",
                                 message=f"parsed {len(script.chapters)} chapter(s), "
                                         f"{sum(len(c.lines) for c in script.chapters)} lines"))
                job.script = script
                job.script_path = script_path
                job.source_path = source_path
            else:
                # Artifacts already present — just load them.
                job.hydrate_artifacts()
                job.mark_stage("ingest", "skipped", message="already on disk")
                job.mark_stage("parse", "skipped", message="already on disk")
                log.info("resume: skipping ingest+parse (artifacts present)")

            if job.script is None or job.script_path is None:
                job.hydrate_artifacts()

            # Update summary fields.
            if job.script is not None:
                job.persist.title = job.script.title
                job.persist.n_chapters = len(job.script.chapters)
                job.persist.n_lines = sum(len(c.lines) for c in job.script.chapters)
                job.save()

            # --- stage: cast (may be skipped on resume) -------------
            cast_path = build_dir / "cast.json"
            if skip_to in (None, "ingest", "parse", "cast") or not cast_path.exists():
                cb(ProgressEvent(stage="cast", phase="start", message="proposing voices"))
                from pipeline.cast import propose, write_cast
                from ui.services.backend_pool import get_backend as _get_pool_backend
                pool_backend = _get_pool_backend(job.backend)
                cast, proposals = propose(
                    job.script_path, build_dir / "cast_samples", job.backend,
                    backend=pool_backend,
                )
                write_cast(cast, cast_path)
                job.cast = cast
                job.cast_path = cast_path
                job.proposals = proposals
                cb(ProgressEvent(
                    stage="cast", phase="done",
                    message=f"voices proposed for {len(proposals)} character(s)",
                    extra={"redirect": f"/voices/{job.job_id}"},
                ))
            else:
                job.hydrate_artifacts()
                job.mark_stage("cast", "skipped", message="cast.json on disk")
                # Still navigate to voices page so the user can review.
                cb(ProgressEvent(
                    stage="cast", phase="done",
                    message="cast reused from previous run",
                    extra={"redirect": f"/voices/{job.job_id}"},
                ))

            job.status = "voices"
            job.error = None
        except MissingDependency as e:
            job.status = "error"
            job.error = f"{e}\n  fix: {e.install}"
            cb(ProgressEvent(stage="error", phase="error", message=job.error))
        except ConfigurationError as e:
            job.status = "error"
            fix = f"  fix: {e.fix}" if e.fix else ""
            job.error = f"{e}\n{fix}"
            cb(ProgressEvent(stage="error", phase="error", message=job.error))
        except Exception as e:
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            log.exception("parse worker failed")
            cb(ProgressEvent(stage="error", phase="error", message=job.error))

    t = threading.Thread(target=worker, name=f"parse-{job.job_id}", daemon=True)
    job._thread = t
    t.start()


def _start_render(job: Job) -> None:
    """Run render + package on a background thread; push events into job queue."""
    loop = asyncio.get_running_loop()
    if job._queue is None:
        job._queue = asyncio.Queue()
    raw_cb = make_threadsafe_callback(loop, job._queue)
    cb = _make_ui_callback(job, raw_cb)

    def worker():
        try:
            # Re-hydrate artifacts from disk if we're resuming.
            if job.script_path is None or job.cast_path is None:
                job.hydrate_artifacts()
            assert job.script_path and job.cast_path and job.build_dir, (
                "render requires script.json + cast.json + build_dir"
            )
            cb(ProgressEvent(stage="render", phase="start", message="loading voice engine"))
            from pipeline.render import render_all
            from ui.services.backend_pool import get_backend as _pool
            # Seed render_all with the UI's shared backend so we don't
            # load MLX / Chatterbox twice per process.
            seeded = {job.backend: _pool(job.backend)}
            chapter_mp3s = render_all(
                script_path=job.script_path,
                cast_path=job.cast_path,
                backend_name=job.backend,
                build_dir=job.build_dir,
                on_progress=cb,
                backends=seeded,
            )
            cb(ProgressEvent(stage="render", phase="done",
                             message=f"rendered {len(chapter_mp3s)} chapter(s)"))
            cb(ProgressEvent(stage="package", phase="start",
                             message=f"building .{job.output_format}"))
            from pipeline.package import package
            out_dir = REPO / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = package(
                script_path=job.script_path,
                chapter_mp3s=chapter_mp3s,
                out_dir=out_dir,
                format=job.output_format,  # type: ignore[arg-type]
                build_dir=job.build_dir,
                title=(job.script.title if job.script else None),
                author=None,
                cover_path=job.cover_path,
            )
            job.persist.output_path = str(out_path)
            job.status = "done"
            job.error = None
            cb(ProgressEvent(
                stage="package", phase="done",
                message=f"wrote {out_path.name}",
                extra={
                    "output_path": str(out_path),
                    "redirect": f"/done/{job.job_id}",
                },
            ))
        except MissingDependency as e:
            job.status = "error"
            job.error = f"{e}\n  fix: {e.install}"
            cb(ProgressEvent(stage="error", phase="error", message=job.error))
        except ConfigurationError as e:
            job.status = "error"
            fix = f"  fix: {e.fix}" if e.fix else ""
            job.error = f"{e}\n{fix}"
            cb(ProgressEvent(stage="error", phase="error", message=job.error))
        except Exception as e:
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            log.exception("render worker failed")
            cb(ProgressEvent(stage="error", phase="error", message=job.error))

    t = threading.Thread(target=worker, name=f"render-{job.job_id}", daemon=True)
    job._thread = t
    t.start()


# --- pages ----------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def page_upload(request: Request):
    settings = current_settings
    provider_ok = settings.has_key_for(settings.provider)
    return _render(
        "upload.html",
        request,
        settings=settings.public_view(),
        provider_ok=provider_ok,
    )


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return _render("settings.html", request, settings=current_settings.public_view())


@app.get("/parsing/{job_id}", response_class=HTMLResponse)
def page_parsing(request: Request, job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        return RedirectResponse("/", status_code=303)
    return _render("parsing.html", request, job=job.public_view())


@app.get("/voices/{job_id}", response_class=HTMLResponse)
def page_voices(request: Request, job_id: str):
    job = session_mgr.get(job_id)
    if job is None or job.script is None:
        return RedirectResponse("/", status_code=303)
    return _render(
        "voices.html",
        request,
        job=job.public_view(),
        settings=current_settings.public_view(),
    )


@app.get("/options/{job_id}", response_class=HTMLResponse)
def page_options(request: Request, job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        return RedirectResponse("/", status_code=303)
    return _render(
        "options.html",
        request,
        job=job.public_view(),
        backends=_backends_available(),
    )


@app.get("/rendering/{job_id}", response_class=HTMLResponse)
def page_rendering(request: Request, job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        return RedirectResponse("/", status_code=303)
    return _render("rendering.html", request, job=job.public_view())


@app.get("/done/{job_id}", response_class=HTMLResponse)
def page_done(request: Request, job_id: str):
    job = session_mgr.get(job_id)
    if job is None or job.output_path is None:
        return RedirectResponse("/", status_code=303)
    return _render("done.html", request, job=job.public_view())


# --- actions --------------------------------------------------------------


@app.post("/api/settings")
def api_save_settings(
    provider: str = Form("anthropic"),
    anthropic_api_key: str = Form(""),
    gemini_api_key: str = Form(""),
    anthropic_model: str = Form(""),
    gemini_model: str = Form(""),
    backend: str = Form("mlx-kokoro"),
    output_format: str = Form("m4b"),
    theme: str = Form("system"),
):
    global current_settings
    # Keep any existing saved key when the user posts a placeholder/redaction
    # instead of a fresh value.
    def keep_if_placeholder(existing: str, posted: str) -> str:
        if not posted or posted.startswith("•"):
            return existing
        return posted

    current_settings = Settings(
        provider=provider,  # type: ignore[arg-type]
        anthropic_api_key=keep_if_placeholder(current_settings.anthropic_api_key, anthropic_api_key),
        gemini_api_key=keep_if_placeholder(current_settings.gemini_api_key, gemini_api_key),
        anthropic_model=anthropic_model,
        gemini_model=gemini_model,
        backend=backend,
        output_format=output_format,  # type: ignore[arg-type]
        theme=theme,  # type: ignore[arg-type]
    )
    save_settings(current_settings)
    current_settings.apply_to_env()
    return RedirectResponse("/", status_code=303)


@app.post("/api/upload")
async def api_upload(request: Request, file: UploadFile = File(...)):
    if file.filename is None:
        raise HTTPException(400, "No file uploaded")
    settings = current_settings
    if not settings.has_key_for(settings.provider):
        raise HTTPException(400, f"No API key configured for provider {settings.provider!r}. "
                                 f"Go to /settings.")

    path = _save_upload(file)
    job = session_mgr.new_job()
    job.persist.input_path = str(path)
    job.persist.input_filename = Path(file.filename).name
    job.persist.provider = settings.provider
    job.persist.backend = settings.backend
    job.persist.output_format = settings.output_format
    job.persist.status = "parsing"
    job.save()

    provider_model = (
        settings.anthropic_model if settings.provider == "anthropic"
        else settings.gemini_model if settings.provider == "gemini"
        else ""
    ) or None

    _start_parse(job, settings.provider, provider_model)
    return RedirectResponse(f"/parsing/{job.job_id}", status_code=303)


@app.post("/api/voice-swap/{job_id}")
def api_voice_swap(job_id: str, character: str = Form(...), voice_id: str = Form(...)):
    job = session_mgr.get(job_id)
    if job is None or job.cast is None or job.cast_path is None:
        raise HTTPException(404, "job not found")
    if character not in job.cast.mapping:
        raise HTTPException(400, f"unknown character {character!r}")
    # Preserve CastEntry shape if present.
    existing = job.cast.mapping[character]
    if hasattr(existing, "voice"):
        existing.voice = voice_id  # type: ignore[attr-defined]
    else:
        job.cast.mapping[character] = voice_id
    # Persist.
    from pipeline.cast import write_cast
    write_cast(job.cast, job.cast_path)
    return JSONResponse({"ok": True, "character": character, "voice_id": voice_id})


@app.get("/api/audition")
def api_audition(backend: str, voice_id: str, text: str):
    """Return a cached WAV audition. Used by the voice picker to play
    samples in-browser."""
    if not text:
        text = "I think I shall take the long way home today."
    try:
        path = audition(backend, voice_id, text[:300])
    except MissingDependency as e:
        raise HTTPException(503, f"{e}\nfix: {e.install}")
    except Exception as e:
        log.exception("audition failed")
        raise HTTPException(500, f"audition failed: {e}")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voices/{backend}")
def api_list_voices(backend: str):
    """Return the full voice list for a backend — used by the picker
    sheet to show alternatives beyond the top-3 proposals."""
    try:
        b = get_backend(backend)
        return JSONResponse([
            {
                "id": v.id, "display_name": v.display_name,
                "gender": v.gender, "age": v.age, "accent": v.accent,
                "tags": v.tags,
            }
            for v in b.list_voices()
        ])
    except MissingDependency as e:
        raise HTTPException(503, f"{e}\nfix: {e.install}")


@app.post("/api/options/{job_id}")
async def api_options(
    job_id: str,
    output_format: str = Form("m4b"),
    backend: str = Form("mlx-kokoro"),
    cover: Optional[UploadFile] = File(None),
):
    job = session_mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if output_format not in ("m4b", "epub3"):
        raise HTTPException(400, f"bad output_format {output_format!r}")
    job.persist.output_format = output_format
    job.persist.backend = backend
    if cover is not None and cover.filename:
        cover_path = _cover_path_from_upload(job, cover)
        if cover_path:
            job.persist.cover_path = str(cover_path)
    job.save()
    return RedirectResponse(f"/rendering/{job_id}", status_code=303)


@app.post("/api/render/{job_id}")
async def api_start_render(job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    # Promote to active so subsequent calls hit the in-memory instance.
    session_mgr.set_active(job)
    job.status = "rendering"
    # Reset the queue for the render stage (prior parse queue is drained).
    job._queue = asyncio.Queue()
    _start_render(job)
    return JSONResponse({"ok": True})


# --- history + resume -----------------------------------------------------


@app.get("/history", response_class=HTMLResponse)
def page_history(request: Request):
    jobs = session_mgr.all_persisted()
    return _render(
        "history.html",
        request,
        jobs=[j.public_view() for j in jobs],
        settings=current_settings.public_view(),
    )


@app.post("/api/resume/{job_id}")
async def api_resume(job_id: str):
    """Restart a failed / abandoned job from its last-good stage."""
    job = session_mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.build_dir is None or job.input_path is None:
        raise HTTPException(400, "job is missing build_dir or input_path; cannot resume")
    if not Path(job.input_path).exists():
        raise HTTPException(400, f"input file no longer exists: {job.input_path}")
    if not job.build_dir.exists():
        job.build_dir.mkdir(parents=True, exist_ok=True)

    session_mgr.set_active(job)
    # Clear stale error state; stages that completed stay as "done", in-progress
    # stage gets re-run.
    job.persist.error = None
    # Detect where to restart.
    resume_stage = detect_last_good_stage(job.build_dir)
    log.info("resume job=%s from stage=%s", job.job_id, resume_stage)
    # Reset the queue for the resumed run.
    job._queue = asyncio.Queue()

    if resume_stage in ("ingest", "parse", "cast"):
        job.status = "parsing"
        job.save()
        provider_model = (
            current_settings.anthropic_model if job.provider == "anthropic"
            else current_settings.gemini_model if job.provider == "gemini"
            else ""
        ) or None
        _start_parse(job, job.provider, provider_model, skip_to=resume_stage)
        return RedirectResponse(f"/parsing/{job.job_id}", status_code=303)

    if resume_stage in ("render", "package"):
        job.hydrate_artifacts()
        job.status = "rendering"
        job.save()
        _start_render(job)
        return RedirectResponse(f"/rendering/{job.job_id}", status_code=303)

    # Everything's done on disk already — just show the done page.
    job.status = "done"
    job.save()
    return RedirectResponse(f"/done/{job.job_id}", status_code=303)


@app.post("/api/job/{job_id}/delete")
async def api_delete_job(job_id: str, remove_build: bool = Form(False)):
    """Delete a job record. Optionally also remove its build directory."""
    ok = session_mgr.delete(job_id, remove_build=remove_build)
    if not ok:
        raise HTTPException(404, "job not found")
    return RedirectResponse("/history", status_code=303)


@app.get("/download/{job_id}")
def download(job_id: str):
    job = session_mgr.get(job_id)
    if job is None or job.output_path is None:
        raise HTTPException(404, "job or output not found")
    return FileResponse(
        job.output_path,
        filename=job.output_path.name,
        media_type=(
            "audio/mp4" if job.output_format == "m4b"
            else "application/epub+zip"
        ),
    )


# --- SSE progress stream --------------------------------------------------


@app.get("/events/{job_id}")
async def events(job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    # Pre-render queue setup for cases where /events is hit before a stage starts.
    if job._queue is None:
        job._queue = asyncio.Queue()
    queue = job._queue

    async def gen():
        async for chunk in stream_events(queue):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # if ever fronted by nginx
        },
    )


@app.get("/api/job/{job_id}")
def api_job_state(job_id: str):
    job = session_mgr.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return JSONResponse(job.public_view())
