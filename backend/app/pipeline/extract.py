from app.core.config import get_settings
from app.pipeline.fill import fill_from_page
from app.pipeline.scores import stamp
from app.pipeline.parse import merge_documents, parse_read
from app.pipeline.read_text import ReadText, read_bytes
from app.schemas.documents import Extraction
from app.services.storage import read_stored

_MODEL_NOTE = "The layout parser missed a required field, so the local model read the page."


def extract_file(file_id: str) -> Extraction:
    stored = read_stored(file_id)
    if stored is None:
        return Extraction(
            file_id=file_id,
            confidence=0,
            completeness=0,
            warnings=["File not found."],
            extractor="missing",
        )
    summary, data = stored
    return extract_bytes(file_id, data, source_name=summary.name)


def extract_bytes(file_id: str, data: bytes, source_name: str | None = None) -> Extraction:
    read = read_bytes(data, source_name or file_id)
    return extract_read(file_id, source_name, read)


def extract_read(file_id: str, source_name: str | None, read: ReadText, **kwargs) -> Extraction:
    """Read with the layout parser. Call the model only when a required field is missing."""
    parsed = parse_read(file_id, source_name, read)
    if not read.text.strip() or not _needs_model(parsed, source=read.source):
        return parsed
    if len(read.pages) > 1 and len(read.text) > get_settings().model_max_chars:
        return _fill_long(file_id, source_name, read, parsed, **kwargs)
    return _prefer_model(parsed, fill_from_page(file_id, source_name, read, **kwargs))


def _fill_long(file_id: str, source_name: str | None, read: ReadText, parsed: Extraction, **kwargs) -> Extraction:
    """A long receipt is sent in page groups that fit the model, then merged."""
    documents = []
    warnings = list(parsed.warnings)
    input_tokens = 0
    output_tokens = 0
    extractor = parsed.extractor
    for group in _page_groups(read.pages, get_settings().model_max_chars):
        slice_read = ReadText(
            text="\n".join(group),
            source=read.source,
            ocr_confidence=read.ocr_confidence,
        )
        sliced = parse_read(file_id, source_name, slice_read)
        if sliced.document is not None and not _needs_model(sliced, source=read.source):
            documents.append(sliced.document)
            continue
        filled = fill_from_page(file_id, source_name, slice_read, **kwargs)
        warnings.extend(filled.warnings)
        input_tokens += filled.input_tokens
        output_tokens += filled.output_tokens
        if filled.extractor:
            extractor = filled.extractor
        if filled.document is not None:
            documents.append(filled.document)
    merged, confidence = merge_documents(documents)
    if merged is None:
        return parsed.model_copy(
            update={"warnings": [_MODEL_NOTE, *warnings], "input_tokens": input_tokens, "output_tokens": output_tokens}
        )
    return stamp(
        Extraction(
            file_id=file_id,
            source_name=source_name,
            document_type=merged.document_type,
            confidence=confidence,
            document=merged,
            warnings=[_MODEL_NOTE, *warnings],
            extractor=extractor,
            ocr_confidence=read.ocr_confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        source=read.source,
        ocr_confidence=read.ocr_confidence,
        model=input_tokens > 0 or output_tokens > 0,
    )


def _page_groups(pages: list[str], budget: int) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    limit = max(int(budget), 1)
    for page in pages:
        if current and size + len(page) > limit:
            groups.append(current)
            current = []
            size = 0
        current.append(page)
        size += len(page)
    if current:
        groups.append(current)
    return groups


def _prefer_model(parsed: Extraction, filled: Extraction) -> Extraction:
    if filled.document is not None:
        return filled.model_copy(update={"warnings": [_MODEL_NOTE, *parsed.warnings, *filled.warnings]})
    if parsed.document is not None:
        return parsed.model_copy(update={"warnings": [*parsed.warnings, _MODEL_NOTE, *filled.warnings]})
    return filled.model_copy(update={"warnings": [_MODEL_NOTE, *parsed.warnings, *filled.warnings]})


def _needs_model(extraction: Extraction, *, source: str = "") -> bool:
    document = extraction.document
    if document is None:
        return True
    if not document.line_items or document.total is None:
        return True
    if document.document_date is None and source == "ocr":
        return True
    if document.document_type != "purchase_order" and not document.po_number:
        return True
    return False
