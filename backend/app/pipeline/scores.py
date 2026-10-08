"""Turn a read and a rule list into the four scores the router keeps apart."""

from app.schemas.documents import Document, Extraction
from app.schemas.pipeline import RuleResult, Scorecard, ValidationIssue

TEXT_LAYER_CONFIDENCE = 1.0
TEXT_LAYER_NO_DATE = 0.95
PHOTO_CAP = 0.90
MODEL_CAP = 0.85


def document_completeness(document: Document | None) -> float:
    if document is None:
        return 0.0
    required = [
        bool(document.document_number),
        bool(document.vendor and document.vendor.name),
        document.total is not None,
        bool(document.currency),
        bool(document.line_items),
    ]
    if document.document_type != "purchase_order":
        required.append(bool(getattr(document, "po_number", None)))
    return round(sum(1 for item in required if item) / len(required), 4)


def extraction_confidence(
    *,
    source: str,
    ocr_confidence: float | None,
    completeness: float,
    document: Document | None = None,
    model: bool = False,
) -> float:
    """Trust in the characters, independent of how many fields were filled."""
    if completeness <= 0:
        return 0.0
    if model:
        return MODEL_CAP
    if source == "ocr":
        # An engine that does not report a score still sits on the photograph cap.
        measured = PHOTO_CAP if ocr_confidence is None else max(0.0, min(float(ocr_confidence), 1.0))
        return round(min(measured, PHOTO_CAP), 4)
    if document is not None and document.document_date is None:
        return TEXT_LAYER_NO_DATE
    return TEXT_LAYER_CONFIDENCE


def stamp(extraction: Extraction, *, source: str, ocr_confidence: float | None, model: bool = False) -> Extraction:
    if extraction.document is None:
        return extraction.model_copy(update={"completeness": 0.0, "confidence": extraction.confidence})
    completeness = document_completeness(extraction.document)
    confidence = extraction_confidence(
        source=source,
        ocr_confidence=ocr_confidence,
        completeness=completeness,
        document=extraction.document,
        model=model,
    )
    return extraction.model_copy(update={"completeness": completeness, "confidence": confidence})


def case_scores(
    extractions: list[Extraction],
    issues: list[ValidationIssue],
    rules: list[RuleResult],
) -> Scorecard:
    completeness = min((item.completeness for item in extractions), default=0.0)
    extraction = min((item.confidence for item in extractions), default=0.0)
    documented = [item for item in extractions if item.document is not None]
    if not documented or any(issue.code == "extraction_failed" for issue in issues):
        validation = 0.0
    else:
        failures = sum(1 for issue in issues if issue.code != "low_confidence")
        validation = max(0.0, 1 - (failures / len(documented)))
    fails = [rule for rule in rules if rule.status == "FAIL"]
    if any(rule.severity == "HIGH" for rule in fails):
        matching = 0.4
    elif fails:
        matching = 0.75
    else:
        matching = 1.0
    routing = round(min(completeness, extraction, validation, matching), 4)
    return Scorecard(
        completeness=round(completeness, 4),
        extraction=round(extraction, 4),
        validation=round(validation, 4),
        matching=round(matching, 4),
        routing_score=routing,
    )
