import time
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.pipeline.graph import graph_state, invoke_graph, resume_graph, update_graph_state
from app.services.run_store import list_runs, record_run, update_run
from app.schemas.pipeline import ApprovalDecision, DraftUpdate, RunCreate, RunList, RunView
from app.services.storage import read_stored

router = APIRouter(tags=["runs"])
logger = get_logger(__name__)


@router.get("/api/runs", response_model=RunList)
def get_runs() -> RunList:
    return RunList(runs=list_runs())


@router.post("/api/runs", response_model=RunView)
def create_run(body: RunCreate) -> RunView | JSONResponse:
    missing = [file_id for file_id in body.file_ids if read_stored(file_id) is None]
    if missing:
        return JSONResponse({"error": "Unknown file id.", "missing": missing}, status_code=400)
    return start_run(list(dict.fromkeys(body.file_ids)))


@router.get("/api/runs/{run_id}", response_model=RunView)
def get_run(run_id: str) -> RunView | JSONResponse:
    snapshot = _snapshot(run_id)
    if snapshot is None:
        return JSONResponse({"error": "Run not found."}, status_code=404)
    return _view(run_id, snapshot)


@router.post("/api/runs/{run_id}/draft", response_model=RunView)
def update_draft(run_id: str, body: DraftUpdate) -> RunView | JSONResponse:
    snapshot = _snapshot(run_id)
    if snapshot is None:
        return JSONResponse({"error": "Run not found."}, status_code=404)
    if not snapshot.next:
        return JSONResponse({"error": "This run is not waiting for approval."}, status_code=409)
    view = _view(run_id, snapshot)
    if view.email_draft is None:
        return JSONResponse({"error": "This run has no draft to edit."}, status_code=409)
    view.email_draft.subject = body.subject
    view.email_draft.body = body.body
    config = _config(run_id)
    update_graph_state({"email_draft": view.email_draft.model_dump(mode="json")}, config)
    updated = _view(run_id, graph_state(config))
    update_run(updated)
    return updated


@router.post("/api/runs/{run_id}/approval", response_model=RunView)
def approve_run(run_id: str, body: ApprovalDecision) -> RunView | JSONResponse:
    snapshot = _snapshot(run_id)
    if snapshot is None:
        return JSONResponse({"error": "Run not found."}, status_code=404)
    if not snapshot.next:
        return JSONResponse({"error": "This run is not waiting for approval."}, status_code=409)
    decision: dict = {"approved": body.approved, "note": body.note}
    if body.email_draft is not None:
        decision["email_draft"] = body.email_draft.model_dump(mode="json")
    resume_graph(decision, _config(run_id))
    view = _view(run_id, graph_state(_config(run_id)))
    update_run(view)
    logger.info("approval recorded run_id=%s approved=%s", run_id, body.approved)
    return view


def start_run(
    file_ids: list[str],
    label: str | None = None,
    extractions: list[dict] | None = None,
    epoch: int | None = None,
    latencies: list[int] | None = None,
) -> RunView:
    from app.services.intake import is_current

    run_id = str(uuid.uuid4())
    config = _config(run_id)
    started = time.perf_counter()
    payload: dict = {"file_ids": file_ids, "status": "started"}
    if extractions:
        payload["extractions"] = extractions
    if latencies is not None:
        payload["document_latencies"] = latencies
    invoke_graph(payload, config)
    latency_ms = int((time.perf_counter() - started) * 1000)
    snapshot = graph_state(config)
    view = _view(run_id, snapshot)
    if epoch is not None and not is_current(epoch):
        return view
    record_run(view, label=label, file_count=len(file_ids), latency_ms=latency_ms, file_ids=file_ids)
    logger.info(
        "run finished id=%s routing=%s confidence=%s duration_ms=%s",
        view.id,
        view.routing,
        view.confidence,
        latency_ms,
    )
    return view


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _snapshot(run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        return None
    snapshot = graph_state(_config(run_id))
    if not snapshot.values:
        return None
    return snapshot


def _view(run_id: str, snapshot) -> RunView:
    values = snapshot.values or {}
    return RunView(
        id=run_id,
        status=values.get("status") or "unknown",
        routing=values.get("routing"),
        confidence=values.get("confidence"),
        scores=values.get("scores"),
        risk=values.get("risk"),
        resolutions=values.get("resolutions") or [],
        exception_codes=values.get("exception_codes") or [],
        primary_exception=values.get("primary_exception"),
        validation_issues=values.get("validation_issues") or [],
        match=values.get("match"),
        email_draft=values.get("email_draft"),
        extractions=values.get("extractions") or [],
        awaiting_approval=bool(snapshot.next),
        approval=values.get("approval"),
        exceptions=values.get("exceptions") or [],
    )
