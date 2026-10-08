from decimal import Decimal

from app.schemas.documents import Document, Extraction
from app.schemas.pipeline import ValidationIssue

MONEY_FLOOR = Decimal("1.00")
MONEY_RATE = Decimal("0.005")


def money_close(left: Decimal, right: Decimal) -> bool:
    span = max(abs(left), abs(right))
    tolerance = max(MONEY_FLOOR, (span * MONEY_RATE).quantize(Decimal("0.01")))
    return abs(left - right) <= tolerance


def issues_for_extraction(extraction: Extraction) -> list[ValidationIssue]:
    document = extraction.document
    if document is None:
        message = extraction.warnings[0] if extraction.warnings else "No structured fields extracted."
        return [
            ValidationIssue(
                file_id=extraction.file_id,
                code="extraction_failed",
                message=message,
            )
        ]

    issues: list[ValidationIssue] = []
    total_issue = _total_issue(extraction.file_id, document)
    if total_issue is not None:
        issues.append(total_issue)
    return issues


def _total_issue(file_id: str, document: Document) -> ValidationIssue | None:
    amounts = [line.amount for line in document.line_items if line.amount is not None]
    if not amounts or document.total is None:
        return None
    line_sum = sum(amounts, Decimal("0"))
    expected = line_sum + document.tax if document.tax is not None else line_sum
    if money_close(expected, document.total):
        return None
    return ValidationIssue(
        file_id=file_id,
        code="total_mismatch",
        message=f"Header total {document.total} does not match the line items ({expected}).",
    )
