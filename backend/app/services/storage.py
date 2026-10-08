"""Uploaded files and their manifest. Paths stay inside the upload directory."""

import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

from app.core.config import get_settings
from app.schemas.files import FileSummary, RejectedFile, SaveResult, StoredFile

EXTENSION_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_lock = threading.Lock()
_CONTROL_CHARS = re.compile(r"[\u0000-\u001f\u007f]")


def _size_reason(limit: int) -> str:
    megabyte = 1024 * 1024
    if limit >= megabyte and limit % megabyte == 0:
        return f"This file is larger than {limit // megabyte} MB."
    return f"This file is larger than {limit} bytes."


def clean_name(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", base).strip()
    return cleaned[:180] or "file"


def extension_of(name: str) -> str | None:
    dot = name.rfind(".")
    if dot <= 0:
        return None
    ext = name[dot + 1 :].lower()
    return ext if ext in EXTENSION_TYPES else None


def content_disposition(name: str, download: bool) -> str:
    kind = "attachment" if download else "inline"
    fallback = "".join(char if 32 <= ord(char) <= 126 else "_" for char in name)
    fallback = fallback.replace('"', "_").replace("\\", "_")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _manifest_path() -> Path:
    return get_settings().upload_dir / "manifest.json"


def _stored_path(stored_name: str) -> Path:
    root = get_settings().upload_dir.resolve()
    full = (root / stored_name).resolve()
    if full.parent != root:
        raise ValueError("Invalid stored file path")
    return full


def _read_manifest() -> list[StoredFile]:
    path = _manifest_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(raw, list):
        return []
    return [StoredFile.model_validate(item) for item in raw]


def _write_manifest(files: list[StoredFile]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in files]
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def to_summary(stored: StoredFile) -> FileSummary:
    return FileSummary(
        id=stored.id,
        name=stored.name,
        size=stored.size,
        type=stored.type,
        uploaded_at=stored.uploaded_at,
    )


def list_files() -> list[FileSummary]:
    with _lock:
        return [to_summary(item) for item in _read_manifest()]


def read_stored(file_id: str) -> tuple[FileSummary, bytes] | None:
    try:
        uuid.UUID(file_id)
    except ValueError:
        return None
    with _lock:
        match = next((item for item in _read_manifest() if item.id == file_id), None)
        if match is None:
            return None
        try:
            data = _stored_path(match.stored_name).read_bytes()
        except FileNotFoundError:
            return None
    return to_summary(match), data


def save_uploads(incoming: list[tuple[str, bytes]]) -> SaveResult:
    from datetime import datetime, timezone

    settings = get_settings()
    noun = "file" if settings.max_files == 1 else "files"
    limit_reason = f"You can upload {settings.max_files} {noun} at most."
    size_reason = _size_reason(settings.max_file_bytes)

    with _lock:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        existing = _read_manifest()
        rejected: list[RejectedFile] = []
        created: list[StoredFile] = []
        room = settings.max_files - len(existing)

        for original_name, data in incoming:
            name = clean_name(original_name or "file")
            if room <= 0:
                rejected.append(RejectedFile(name=name, reason=limit_reason))
                continue
            ext = extension_of(name)
            if ext is None:
                rejected.append(RejectedFile(name=name, reason="This file type is not supported."))
                continue
            if len(data) == 0:
                rejected.append(RejectedFile(name=name, reason="This file is empty."))
                continue
            if len(data) > settings.max_file_bytes:
                rejected.append(RejectedFile(name=name, reason=size_reason))
                continue

            file_id = str(uuid.uuid4())
            stored_name = f"{file_id}.{ext}"
            _stored_path(stored_name).write_bytes(data)
            created.append(
                StoredFile(
                    id=file_id,
                    name=name,
                    stored_name=stored_name,
                    size=len(data),
                    type=EXTENSION_TYPES[ext],
                    uploaded_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            room -= 1

        files = [*created, *existing]
        if created:
            _write_manifest(files)

    return SaveResult(
        files=[to_summary(item) for item in files],
        added=[to_summary(item) for item in created],
        rejected=rejected,
    )


def clear_files() -> list[FileSummary]:
    with _lock:
        for item in _read_manifest():
            try:
                _stored_path(item.stored_name).unlink()
            except FileNotFoundError:
                pass
        _write_manifest([])
    return []


def delete_file(file_id: str) -> tuple[list[FileSummary], bool]:
    try:
        uuid.UUID(file_id)
    except ValueError:
        with _lock:
            return [to_summary(item) for item in _read_manifest()], False

    with _lock:
        existing = _read_manifest()
        match = next((item for item in existing if item.id == file_id), None)
        if match is None:
            return [to_summary(item) for item in existing], False
        try:
            _stored_path(match.stored_name).unlink()
        except FileNotFoundError:
            pass
        remaining = [item for item in existing if item.id != file_id]
        _write_manifest(remaining)
        return [to_summary(item) for item in remaining], True
