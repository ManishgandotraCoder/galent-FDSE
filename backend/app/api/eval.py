from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.core.config import BACKEND_ROOT
from app.core.logging import get_logger
from app.eval.harness import case_report
from app.services.storage import content_disposition

router = APIRouter(tags=["eval"])
logger = get_logger(__name__)
SAMPLE_DOCUMENTS = BACKEND_ROOT / "sample_data" / "documents"
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@router.get("/api/eval/documents/{name}")
def get_sample_document(name: str) -> Response:
    path = _sample_path(name)
    if path is None:
        return JSONResponse({"error": "Document not found."}, status_code=404)
    data = path.read_bytes()
    return Response(
        content=data,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        headers={
            "Content-Disposition": content_disposition(path.name, False),
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/eval", response_model=None)
def get_eval() -> dict | JSONResponse:
    report = case_report()
    if report is None:
        return JSONResponse({"error": "No cases yet."}, status_code=404)
    return report


@router.post("/api/eval", response_model=None)
def run_eval() -> dict | JSONResponse:
    report = case_report()
    if report is None:
        return JSONResponse({"error": "No cases yet."}, status_code=404)
    logger.info("evaluation read cases=%s documents=%s", report.get("cases"), report.get("documents_processed"))
    return report


def _sample_path(name: str) -> Path | None:
    if not name or name != Path(name).name or name in {".", ".."}:
        return None
    root = SAMPLE_DOCUMENTS.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path
