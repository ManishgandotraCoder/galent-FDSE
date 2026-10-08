"""Background reading after an upload.

Several workers pull from the queue. Each document in a job is read in parallel.
Model calls stay capped in the Ollama client, so a burst waits instead of stampeding.
"""

import json
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
from app.pipeline.extract import extract_file
from app.schemas.files import FileSummary
from app.schemas.intake import IntakeStatus
from app.services.storage import list_files

_lock = threading.Lock()
_queue: queue.Queue[dict] = queue.Queue()
_workers: set[threading.Thread] = set()
_pool: ThreadPoolExecutor | None = None
_active: set[str] = set()
_epoch = 0


def documents_label(count: int) -> str:
    if count == 1:
        return "1 document"
    return f"{count} documents"


def uploaded_message(count: int) -> str:
    if count == 0:
        return ""
    return f"{documents_label(count)} uploaded"


def begin_intake(added: list[FileSummary], rejected: int) -> IntakeStatus:
    if not added:
        return current_intake()
    job = {
        "id": str(uuid.uuid4()),
        "status": "running",
        "total": len(added),
        "processed": 0,
        "accepted": len(added),
        "rejected": rejected,
        "current": added[0].name,
        "message": f"Reading {added[0].name} (1 of {len(added)})",
        "run_id": None,
        "file_ids": [item.id for item in added],
        "names": [item.name for item in added],
    }
    with _lock:
        job["epoch"] = _epoch
        _active.add(job["id"])
        current = _read()
        busy = (
            current is not None
            and current.get("status") == "running"
            and current.get("id") in _active
            and current.get("id") != job["id"]
        )
        if not busy:
            _save(job)
        _queue.put(job)
        _ensure_workers()
    logger.info("intake started files=%s", len(added))
    return current_intake()


def clear_intake() -> None:
    global _epoch
    with _lock:
        _epoch += 1
        _active.clear()
        while True:
            try:
                _queue.get_nowait()
            except queue.Empty:
                break
        try:
            _path().unlink()
        except FileNotFoundError:
            pass


def is_current(epoch: int) -> bool:
    with _lock:
        return epoch == _epoch


def current_intake() -> IntakeStatus:
    uploaded = len(list_files())
    with _lock:
        job = _read()
        if job is None:
            return IntakeStatus(uploaded=uploaded, message=uploaded_message(uploaded))
        if job.get("status") == "running" and job.get("id") not in _active:
            job["status"] = "failed"
            job["message"] = "Processing stopped before it finished."
            _save(job)
    status = job.get("status") or "idle"
    message = str(job.get("message") or "")
    if status in {"done", "idle"}:
        message = uploaded_message(uploaded)
    return IntakeStatus(
        status=status,
        uploaded=uploaded,
        total=int(job.get("total") or 0),
        processed=int(job.get("processed") or 0),
        accepted=int(job.get("accepted") or 0),
        rejected=int(job.get("rejected") or 0),
        current=job.get("current"),
        message=message,
        run_id=job.get("run_id"),
        file_ids=list(job.get("file_ids") or []),
    )


def drain_intake(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            alive = [thread for thread in _workers if thread.is_alive()]
            pending = not _queue.empty()
        if not alive and not pending:
            return
        for thread in alive:
            thread.join(timeout=0.1)
    raise TimeoutError("Background upload processing did not finish.")


def _ensure_workers() -> None:
    """Caller holds `_lock`. Start enough intake threads for `read_workers`."""
    wanted = max(1, get_settings().read_workers)
    alive = {thread for thread in _workers if thread.is_alive()}
    _workers.clear()
    _workers.update(alive)
    while len(_workers) < wanted:
        thread = threading.Thread(target=_loop, name="intake", daemon=True)
        _workers.add(thread)
        thread.start()


def _loop() -> None:
    while True:
        try:
            job = _queue.get(timeout=0.2)
        except queue.Empty:
            with _lock:
                if _queue.empty():
                    _workers.discard(threading.current_thread())
                    return
            continue
        try:
            _process(job)
        except Exception as caught:
            logger.exception("intake failed id=%s", job.get("id"))
            _finish_failed(job, str(caught) or "Processing failed.")
        finally:
            with _lock:
                _active.discard(job["id"])


def _read_pool() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max(1, get_settings().read_workers), thread_name_prefix="read")
        return _pool


def _process(job: dict) -> None:
    from app.api.runs import start_run

    if not _still(job):
        return
    _claim(job)
    names = list(job.get("names") or [])
    file_ids = list(job.get("file_ids") or [])
    total = len(file_ids)
    def read_one(index: int, file_id: str) -> tuple[int, dict | None, int]:
        if not _still(job):
            return index, None, 0
        started = time.perf_counter()
        extraction = extract_file(file_id).model_dump(mode="json")
        return index, extraction, int((time.perf_counter() - started) * 1000)

    futures = [_read_pool().submit(read_one, index, file_id) for index, file_id in enumerate(file_ids)]
    extractions: list[dict | None] = [None] * total
    latencies = [0] * total
    for finished, future in enumerate(futures, start=1):
        index, extraction, latency = future.result()
        if extraction is None:
            return
        extractions[index] = extraction
        latencies[index] = latency
        name = names[index] if index < len(names) else "document"
        _update(
            job,
            status="running",
            processed=finished,
            current=name,
            message=f"Read {finished} of {total} documents",
        )
    if not _still(job):
        return
    _update(job, message=f"Matching {documents_label(total)}")
    view = start_run(file_ids, extractions=extractions, epoch=job.get("epoch"), latencies=latencies)
    if not _still(job):
        return
    uploaded = len(list_files())
    _update(
        job,
        status="done",
        processed=total,
        current=None,
        run_id=view.id,
        message=uploaded_message(uploaded),
    )
    logger.info("intake finished run_id=%s files=%s", view.id, total)


def _finish_failed(job: dict, message: str) -> None:
    _update(job, status="failed", message=message, current=None)


def _claim(job: dict) -> None:
    with _lock:
        current = _read()
        if current is not None and current.get("status") == "running" and current.get("id") not in {None, job["id"]}:
            return
        _save(job)


def _still(job: dict) -> bool:
    with _lock:
        return job.get("epoch") == _epoch


def _update(job: dict, **changes) -> None:
    with _lock:
        if job.get("epoch") != _epoch:
            job.update(changes)
            return
        stored = _read()
        other_running = (
            stored is not None
            and stored.get("status") == "running"
            and stored.get("id") not in {None, job["id"]}
            and changes.get("status") != "done"
        )
        if other_running:
            job.update(changes)
            return
        target = job if stored is None else stored
        target.update(changes)
        job.update(target)
        _save(target)


def _path() -> Path:
    return get_settings().data_dir / "intake.json"


def _read() -> dict | None:
    path = _path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def _save(job: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(job, indent=2), encoding="utf-8")
    temporary.replace(path)
