import sqlite3
import threading
import time
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.core.config import get_settings
from app.core.logging import get_logger
from app.pipeline.extract import extract_file, extract_read
from app.pipeline.match import _ordered, assess, build_email, three_way_match
from app.pipeline.vendor import identity
from app.pipeline.normalize import normalize_extraction
from app.pipeline.read_text import OcrToken, ReadText, read_bytes
from app.pipeline.validate import issues_for_extraction
from app.schemas.documents import Extraction
from app.schemas.pipeline import ExceptionItem, Scorecard, ThreeWayMatch, ValidationIssue
from app.services.storage import read_stored

logger = get_logger(__name__)
_lock = threading.Lock()
_graph = None
_connection: sqlite3.Connection | None = None


class GraphState(TypedDict, total=False):
    file_ids: list[str]
    classified: list[dict]
    extractions: list[dict]
    validation_issues: list[dict]
    match: dict | None
    resolutions: list[dict]
    exception_codes: list[str]
    exceptions: list[dict]
    primary_exception: str | None
    confidence: float
    scores: dict | None
    risk: str | None
    routing: str | None
    email_draft: dict | None
    status: str
    approval: dict | None
    document_latencies: list[int]


def classify_document(state: GraphState) -> dict:
    if state.get("extractions") or state.get("classified"):
        return {"status": "classified"}
    classified: list[dict] = []
    for file_id in state.get("file_ids", []):
        stored = read_stored(file_id)
        if stored is None:
            classified.append(
                {
                    "file_id": file_id,
                    "source_name": None,
                    "text": "",
                    "source": "missing",
                    "ocr_confidence": None,
                    "warnings": ["File not found."],
                }
            )
            continue
        summary, data = stored
        read = read_bytes(data, summary.name)
        classified.append(
            {
                "file_id": file_id,
                "source_name": summary.name,
                "text": read.text,
                "source": read.source,
                "ocr_confidence": read.ocr_confidence,
                "warnings": read.warnings,
                "tokens": [
                    {
                        "text": token.text,
                        "confidence": token.confidence,
                        "xmin": token.xmin,
                        "ymin": token.ymin,
                        "xmax": token.xmax,
                        "ymax": token.ymax,
                    }
                    for token in read.tokens
                ],
            }
        )
    return {"classified": classified, "status": "classified"}


def extract(state: GraphState) -> dict:
    if state.get("extractions"):
        return {"status": "extracted"}
    classified = state.get("classified")
    if not classified:
        extractions = []
        latencies: list[int] = []
        for file_id in state.get("file_ids", []):
            started = time.perf_counter()
            extractions.append(extract_file(file_id).model_dump(mode="json"))
            latencies.append(int((time.perf_counter() - started) * 1000))
        return {"extractions": extractions, "document_latencies": latencies, "status": "extracted"}

    extractions = []
    latencies = []
    for item in classified:
        started = time.perf_counter()
        if item.get("source") == "missing":
            extractions.append(
                Extraction(
                    file_id=item["file_id"],
                    confidence=0,
                    completeness=0,
                    warnings=item.get("warnings") or ["File not found."],
                    extractor="missing",
                ).model_dump(mode="json")
            )
        else:
            read = ReadText(
                text=item.get("text") or "",
                source=item.get("source") or "unknown",
                ocr_confidence=item.get("ocr_confidence"),
                warnings=list(item.get("warnings") or []),
                tokens=[OcrToken(**token) for token in item.get("tokens") or []],
            )
            extractions.append(extract_read(item["file_id"], item.get("source_name"), read).model_dump(mode="json"))
        latencies.append(int((time.perf_counter() - started) * 1000))
    return {"extractions": extractions, "document_latencies": latencies, "status": "extracted"}


def validate(state: GraphState) -> dict:
    issues: list[dict] = []
    for raw in state.get("extractions", []):
        extraction = Extraction.model_validate(raw)
        issues.extend(issue.model_dump(mode="json") for issue in issues_for_extraction(extraction))
    return {"validation_issues": issues, "status": "validated"}


def normalize(state: GraphState) -> dict:
    extractions = [
        normalize_extraction(Extraction.model_validate(raw)).model_dump(mode="json")
        for raw in state.get("extractions", [])
    ]
    return {"extractions": extractions, "status": "normalized"}


def match(state: GraphState) -> dict:
    extractions = [Extraction.model_validate(raw) for raw in state.get("extractions", [])]
    result = three_way_match(extractions)
    return {"match": result.model_dump(mode="json"), "status": "matched"}


def resolve_documents(state: GraphState) -> dict:
    """Record the vendor identity each document will be matched on. Names on the page stay as printed."""
    resolutions: list[dict] = []
    for raw in state.get("extractions", []):
        extraction = Extraction.model_validate(raw)
        if extraction.document is None:
            continue
        resolutions.append(identity(extraction.file_id, extraction.document.vendor))
    return {"resolutions": resolutions, "status": "resolved"}


def risk_assessment(state: GraphState) -> dict:
    """Separate a hard stop from a commercial exception before the score is allowed to clear anything."""
    issues = [ValidationIssue.model_validate(raw) for raw in state.get("validation_issues", [])]
    matched = _matched(state)
    codes = _ordered_codes([issue.code for issue in issues] + list(matched.exceptions))
    hard = {"extraction_failed", "missing_document", "duplicate_invoice"}
    if any(code in hard for code in codes):
        risk = "hard"
    elif codes:
        risk = "soft"
    else:
        risk = "none"
    return {
        "exception_codes": codes,
        "primary_exception": codes[0] if codes else None,
        "risk": risk,
        "status": "assessed",
    }


def calculate_confidence(state: GraphState) -> dict:
    settings = get_settings()
    extractions = [Extraction.model_validate(raw) for raw in state.get("extractions", [])]
    issues = [ValidationIssue.model_validate(raw) for raw in state.get("validation_issues", [])]
    matched = _matched(state)
    result = assess(
        extractions,
        matched,
        issues,
        auto_clear=settings.auto_clear_confidence,
        flag=settings.flag_confidence,
    )
    logger.info(
        "routed confidence=%.2f routing=%s exceptions=%s",
        result.confidence,
        result.routing,
        ",".join(result.exception_codes) or "none",
    )
    return {
        "exception_codes": result.exception_codes,
        "exceptions": [item.model_dump(mode="json") for item in result.exceptions],
        "primary_exception": result.primary_exception,
        "confidence": result.confidence,
        "scores": result.scores.model_dump(mode="json"),
        "risk": result.risk,
        "routing": result.routing,
        "status": "routed",
    }


def _matched(state: GraphState) -> ThreeWayMatch:
    if state.get("match"):
        return ThreeWayMatch.model_validate(state["match"])
    return ThreeWayMatch(status="incomplete", summary="Match did not run.")


def _ordered_codes(codes: list[str]) -> list[str]:
    return _ordered(codes)  # type: ignore[arg-type]


def route(_state: GraphState) -> dict:
    return {}


def next_step(state: GraphState) -> str:
    if state.get("routing") == "auto_clear":
        return "clear"
    return "draft"


def draft(state: GraphState) -> dict:
    matched = ThreeWayMatch.model_validate(state["match"]) if state.get("match") else None
    extractions = [Extraction.model_validate(raw) for raw in state.get("extractions", [])]
    scores = Scorecard.model_validate(state["scores"]) if state.get("scores") else None
    exceptions = [ExceptionItem.model_validate(raw) for raw in state.get("exceptions") or []]
    email = build_email(
        routing=state.get("routing") or "flag",
        primary=state.get("primary_exception"),
        codes=list(state.get("exception_codes") or []),
        match=matched,
        confidence=float(state.get("confidence") or 0),
        extractions=extractions,
        scores=scores,
        exceptions=exceptions,
    )
    return {"email_draft": email.model_dump(mode="json"), "status": "awaiting_approval"}


def approval(state: GraphState) -> dict:
    decision = interrupt(
        {
            "message": "Approve this draft before it can be sent. Nothing is sent automatically.",
            "routing": state.get("routing"),
            "email_draft": state.get("email_draft"),
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    note = decision.get("note") if isinstance(decision, dict) else None
    result: dict = {
        "approval": {"approved": approved, "note": note},
        "status": "approved" if approved else "declined",
    }
    edited = decision.get("email_draft") if isinstance(decision, dict) else None
    if isinstance(edited, dict) and edited.get("subject") and edited.get("body"):
        current = dict(state.get("email_draft") or {})
        current["subject"] = edited["subject"]
        current["body"] = edited["body"]
        current["requires_approval"] = True
        result["email_draft"] = current
    return result


def clear(_state: GraphState) -> dict:
    return {"status": "cleared", "email_draft": None}


def build_graph(checkpointer: BaseCheckpointSaver):
    builder = StateGraph(GraphState)
    builder.add_node("classify_document", classify_document)
    builder.add_node("extract", extract)
    builder.add_node("validate", validate)
    builder.add_node("normalize", normalize)
    builder.add_node("match", match)
    builder.add_node("resolve_documents", resolve_documents)
    builder.add_node("risk_assessment", risk_assessment)
    builder.add_node("calculate_confidence", calculate_confidence)
    builder.add_node("route", route)
    builder.add_node("draft", draft)
    builder.add_node("approval", approval)
    builder.add_node("clear", clear)
    builder.add_edge(START, "classify_document")
    builder.add_edge("classify_document", "extract")
    builder.add_edge("extract", "validate")
    builder.add_edge("validate", "normalize")
    builder.add_edge("normalize", "resolve_documents")
    builder.add_edge("resolve_documents", "match")
    builder.add_edge("match", "risk_assessment")
    builder.add_edge("risk_assessment", "calculate_confidence")
    builder.add_edge("calculate_confidence", "route")
    builder.add_conditional_edges("route", next_step, {"draft": "draft", "clear": "clear"})
    builder.add_edge("draft", "approval")
    builder.add_edge("approval", END)
    builder.add_edge("clear", END)
    return builder.compile(checkpointer=checkpointer)


def get_graph():
    global _graph, _connection
    if _graph is not None:
        return _graph
    with _lock:
        if _graph is None:
            settings = get_settings()
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            _connection = sqlite3.connect(settings.data_dir / "checkpoints.sqlite", check_same_thread=False)
            _graph = build_graph(SqliteSaver(_connection))
    return _graph


def reset_graph() -> None:
    global _graph, _connection
    with _lock:
        if _connection is not None:
            _connection.close()
        _connection = None
        _graph = None


def discard_checkpoints() -> None:
    reset_graph()
    data = get_settings().data_dir
    for name in ("checkpoints.sqlite", "checkpoints.sqlite-wal", "checkpoints.sqlite-shm"):
        try:
            (data / name).unlink()
        except FileNotFoundError:
            pass


def invoke_graph(payload, config):
    graph = get_graph()
    with _lock:
        return graph.invoke(payload, config)


def graph_state(config):
    graph = get_graph()
    with _lock:
        return graph.get_state(config)


def resume_graph(decision: dict, config):
    return invoke_graph(Command(resume=decision), config)


def update_graph_state(values: dict, config) -> None:
    graph = get_graph()
    with _lock:
        graph.update_state(config, values)
