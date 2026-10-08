"""The case list saved on disk. One row per pipeline run."""

import json
import threading
from pathlib import Path

from app.core.config import get_settings
from app.schemas.pipeline import RunSummary, RunView

_lock = threading.Lock()


def _path() -> Path:
    return get_settings().data_dir / "runs.json"


def _read() -> list[dict]:
    path = _path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return raw if isinstance(raw, list) else []


def _write(rows: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    temporary.replace(path)


def clear_runs() -> None:
    with _lock:
        _write([])


def list_runs() -> list[RunSummary]:
    with _lock:
        rows = _read()
    return [RunSummary.model_validate(row) for row in rows]


def record_run(
    view: RunView,
    *,
    label: str | None,
    file_count: int,
    latency_ms: int | None,
    file_ids: list[str] | None = None,
) -> RunSummary:
    summary = _summary(view, label=label, file_count=file_count, latency_ms=latency_ms, file_ids=file_ids)
    with _lock:
        rows = [row for row in _read() if row.get("id") != view.id]
        rows.insert(0, summary.model_dump(mode="json"))
        _write(rows)
    return summary


def update_run(view: RunView) -> None:
    with _lock:
        rows = _read()
        for index, row in enumerate(rows):
            if row.get("id") != view.id:
                continue
            refreshed = _summary(
                view,
                label=row.get("label"),
                file_count=int(row.get("file_count") or 0),
                latency_ms=row.get("latency_ms"),
                file_ids=list(row.get("file_ids") or []),
            )
            rows[index] = refreshed.model_dump(mode="json")
            _write(rows)
            return


def _summary(
    view: RunView,
    *,
    label: str | None,
    file_count: int,
    latency_ms: int | None,
    file_ids: list[str] | None = None,
) -> RunSummary:
    match = view.match
    ids, names = _documents(view, file_ids)
    return RunSummary(
        id=view.id,
        label=label,
        status=view.status,
        routing=view.routing,
        confidence=view.confidence,
        exception_codes=view.exception_codes,
        primary_exception=view.primary_exception,
        awaiting_approval=view.awaiting_approval,
        po_number=match.po_number if match else None,
        invoice_number=match.invoice_number if match else None,
        vendor_name=match.vendor_name if match else None,
        invoice_total=match.invoice_total if match else None,
        currency=match.currency if match else None,
        file_count=file_count,
        file_ids=ids,
        source_names=names,
        latency_ms=latency_ms,
    )


def _documents(view: RunView, file_ids: list[str] | None) -> tuple[list[str], list[str]]:
    ids = list(file_ids or [])
    names: list[str] = []
    for raw in view.extractions:
        if not isinstance(raw, dict):
            continue
        file_id = raw.get("file_id")
        if isinstance(file_id, str) and file_id not in ids:
            ids.append(file_id)
        name = raw.get("source_name")
        if isinstance(name, str) and name:
            names.append(name)
    return ids, names
