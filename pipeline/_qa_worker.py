"""Background Whisper QA worker — the safe parallelism for Chatterbox renders.

Chatterbox synthesis is MPS-bound; Whisper transcription is CPU-bound.  They
share no hardware resource, so overlapping them is a free 1.3–1.5× effective
throughput gain (unlike a second Chatterbox process which regressed 38% via
MPS queue contention — see STORY.md 2026-04-17).

Usage (from render_chapter):

    worker = QAWorker(audit_path=build_dir / "qa_audit.jsonl")
    worker.start()
    # ... after each line synthesis:
    worker.enqueue(wav_path, expected_text, chapter, idx)
    # ... after render_chapter finishes:
    worker.stop()

The worker writes one JSON line per flagged result to ``audit_path``.  On the
Done screen the UI checks for this file and surfaces a summary if any lines
failed.  No retry logic here — that earns complexity only after the audit log
has shown which shapes actually trip it (see BACKLOG).
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

# Similarity below which a line is flagged in the audit log.
SIM_THRESHOLD = 0.70

_SENTINEL = object()


@dataclass
class _QATask:
    wav: Path
    expected: str
    chapter: int
    idx: int


class QAWorker:
    """Single-consumer thread that transcribes synthesised WAVs with Whisper
    while the render loop continues synthesising the next line.

    If faster-whisper is not installed, the worker silently becomes a no-op
    (enqueue / stop do nothing, no audit file is written).
    """

    def __init__(
        self,
        audit_path: Path,
        threshold: float = SIM_THRESHOLD,
        whisper_model: str = "base.en",
    ) -> None:
        self._audit = audit_path
        self._threshold = threshold
        self._model_name = whisper_model
        self._q: queue.Queue = queue.Queue(maxsize=32)
        self._thread: Optional[threading.Thread] = None
        self._available = False

    def start(self) -> None:
        """Start the background thread.  Silently disables if Whisper missing."""
        try:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(
                self._model_name, device="cpu", compute_type="int8"
            )
            self._available = True
        except ImportError:
            log.debug("faster-whisper not installed — QA worker disabled")
            return

        self._thread = threading.Thread(
            target=self._run, name="qa-whisper-worker", daemon=True
        )
        self._thread.start()
        log.debug("QA worker started (model=%s, threshold=%.2f)", self._model_name, self._threshold)

    def enqueue(self, wav: Path, expected: str, chapter: int, idx: int) -> None:
        if not self._available:
            return
        try:
            self._q.put_nowait(_QATask(wav=wav, expected=expected, chapter=chapter, idx=idx))
        except queue.Full:
            log.debug("QA worker queue full — dropping line ch%02d/%d", chapter, idx)

    def stop(self) -> None:
        """Signal worker to finish remaining queue items then exit."""
        if not self._available or self._thread is None:
            return
        self._q.put(_SENTINEL)
        self._thread.join(timeout=120)
        log.debug("QA worker stopped")

    def _run(self) -> None:
        import re
        import difflib

        def _norm(s: str) -> list[str]:
            return re.sub(r"[^\w\s]", " ", s.lower()).split()

        while True:
            item = self._q.get()
            if item is _SENTINEL:
                break
            try:
                segs, _ = self._whisper.transcribe(
                    str(item.wav), beam_size=1, language="en"
                )
                heard = " ".join(s.text.strip() for s in segs)
                ratio = difflib.SequenceMatcher(
                    None, _norm(item.expected), _norm(heard)
                ).ratio()
                if ratio < self._threshold:
                    entry = {
                        "chapter": item.chapter,
                        "idx": item.idx,
                        "expected": item.expected[:120],
                        "heard": heard[:120],
                        "sim": round(ratio, 3),
                    }
                    log.warning(
                        "QA ch%02d/%d sim=%.3f — expected: %r heard: %r",
                        item.chapter, item.idx, ratio,
                        item.expected[:60], heard[:60],
                    )
                    with self._audit.open("a") as f:
                        f.write(json.dumps(entry) + "\n")
            except Exception as exc:
                log.debug("QA worker error on ch%02d/%d: %s", item.chapter, item.idx, exc)
