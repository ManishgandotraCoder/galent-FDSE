from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.intake import begin_intake, clear_intake
from app.pipeline.graph import discard_checkpoints
from app.services.run_store import clear_runs
from app.schemas.files import FileListResponse
from app.services.storage import clear_files, content_disposition, delete_file, list_files, read_stored, save_uploads

router = APIRouter(tags=["files"])
logger = get_logger(__name__)


@router.post("/api/clear")
def post_clear() -> dict[str, bool]:
    clear_intake()
    discard_checkpoints()
    clear_files()
    clear_runs()
    logger.info("uploads and cases cleared")
    return {"cleared": True}


@router.get("/api/files", response_model=FileListResponse, response_model_exclude_none=True)
def get_files() -> FileListResponse:
    settings = get_settings()
    return FileListResponse(files=list_files(), limit=settings.max_files)


@router.post("/api/files", response_model=FileListResponse, response_model_exclude_none=True)
async def post_files(files: list[UploadFile] = File(default=[])) -> FileListResponse | JSONResponse:
    if not files:
        return JSONResponse({"error": "Choose at least one file."}, status_code=400)

    settings = get_settings()
    incoming: list[tuple[str, bytes]] = []
    for upload in files:
        incoming.append((upload.filename or "file", await _read_capped(upload, settings.max_file_bytes)))

    result = save_uploads(incoming)
    logger.info("upload accepted=%s rejected=%s", len(result.added), len(result.rejected))
    if result.added:
        begin_intake(result.added, rejected=len(result.rejected))
    body = FileListResponse(
        files=result.files,
        added=result.added,
        rejected=result.rejected,
        limit=settings.max_files,
    )
    status = 200 if result.added else 400
    return JSONResponse(body.model_dump(mode="json", by_alias=True, exclude_none=True), status_code=status)


@router.get("/api/files/{file_id}")
def get_file(file_id: str, download: str | None = None) -> Response:
    stored = read_stored(file_id)
    if stored is None:
        return JSONResponse({"error": "File not found."}, status_code=404)
    summary, data = stored
    return Response(
        content=data,
        media_type=summary.type,
        headers={
            "Content-Disposition": content_disposition(summary.name, download == "1"),
            "Content-Length": str(len(data)),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/api/files/{file_id}", response_model=FileListResponse, response_model_exclude_none=True)
def remove_file(file_id: str) -> FileListResponse | JSONResponse:
    files, removed = delete_file(file_id)
    if not removed:
        return JSONResponse({"error": "File not found."}, status_code=404)
    return FileListResponse(files=files, limit=get_settings().max_files)


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await upload.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > limit:
            return b"\0" * (limit + 1)
        chunks.append(block)
    return b"".join(chunks)
