from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ExceptionCode = Literal[
    "extraction_failed",
    "missing_document",
    "duplicate_invoice",
    "potential_duplicate",
    "resubmission",
    "po_mismatch",
    "vendor_mismatch",
    "currency_mismatch",
    "total_mismatch",
    "tax_mismatch",
    "price_mismatch",
    "quantity_mismatch",
    "partial_delivery",
    "low_confidence",
]

SEVERITY: tuple[ExceptionCode, ...] = (
    "extraction_failed",
    "missing_document",
    "duplicate_invoice",
    "potential_duplicate",
    "resubmission",
    "po_mismatch",
    "vendor_mismatch",
    "currency_mismatch",
    "total_mismatch",
    "tax_mismatch",
    "price_mismatch",
    "quantity_mismatch",
    "partial_delivery",
    "low_confidence",
)

VENDOR_EMAIL_CODES: frozenset[ExceptionCode] = frozenset(
    {
        "vendor_mismatch",
        "currency_mismatch",
        "total_mismatch",
        "tax_mismatch",
        "price_mismatch",
        "quantity_mismatch",
        "partial_delivery",
        "po_mismatch",
    }
)

# A hard exception is rejected even when the read itself looks perfect.
# Everything else commercial waits for a person. Confidence is consulted only
# when no exception was found.
HARD_EXCEPTIONS: frozenset[ExceptionCode] = frozenset(
    {
        "extraction_failed",
        "missing_document",
        "duplicate_invoice",
    }
)

Routing = Literal["auto_clear", "flag", "reject"]
MatchStatus = Literal["matched", "exception", "incomplete"]


class ValidationIssue(BaseModel):
    file_id: str
    code: ExceptionCode
    message: str


class MatchCheck(BaseModel):
    label: str
    passed: bool


class RuleResult(BaseModel):
    """One deterministic check. The model may explain it. The model does not decide it."""

    rule: str
    status: Literal["PASS", "FAIL", "WARN"]
    expected: str | None = None
    actual: str | None = None
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    reason: str
    code: ExceptionCode | None = None


class ExceptionItem(BaseModel):
    type: ExceptionCode
    severity: Literal["high", "medium"]
    message: str


class LineComparison(BaseModel):
    key: str
    description: str
    po_quantity: Decimal | None = None
    invoice_quantity: Decimal | None = None
    received_quantity: Decimal | None = None
    po_unit_price: Decimal | None = None
    invoice_unit_price: Decimal | None = None
    status: Literal["matched", "exception"]
    notes: list[str] = Field(default_factory=list)


class ThreeWayMatch(BaseModel):
    status: MatchStatus
    po_number: str | None = None
    invoice_number: str | None = None
    grn_number: str | None = None
    vendor_name: str | None = None
    currency: str | None = None
    po_total: Decimal | None = None
    invoice_total: Decimal | None = None
    grn_total: Decimal | None = None
    exceptions: list[ExceptionCode] = Field(default_factory=list)
    lines: list[LineComparison] = Field(default_factory=list)
    checks: list[MatchCheck] = Field(default_factory=list)
    rules: list[RuleResult] = Field(default_factory=list)
    summary: str


class Scorecard(BaseModel):
    """Four different questions, kept apart on purpose.

    Completeness asks whether the required fields were found.
    Extraction asks how trustworthy the characters are.
    Validation asks whether the document agrees with itself.
    Matching asks whether the PO, invoice, and goods receipt agree.
    The routing score is the weakest of the four, so a strong field cannot hide a weak one.
    """

    completeness: float = Field(ge=0, le=1)
    extraction: float = Field(ge=0, le=1)
    validation: float = Field(ge=0, le=1)
    matching: float = Field(ge=0, le=1)
    routing_score: float = Field(ge=0, le=1)


class EmailDraft(BaseModel):
    to_role: Literal["vendor", "approver"]
    subject: str
    body: str
    requires_approval: bool = True


class Assessment(BaseModel):
    exception_codes: list[ExceptionCode]
    primary_exception: ExceptionCode | None
    confidence: float = Field(ge=0, le=1)
    scores: Scorecard
    risk: Literal["none", "soft", "hard"]
    routing: Routing
    exceptions: list[ExceptionItem] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None
    email_draft: EmailDraft | None = None


class ApprovalRecord(BaseModel):
    approved: bool
    note: str | None = None


class RunCreate(BaseModel):
    file_ids: list[str] = Field(min_length=1)


class RunView(BaseModel):
    id: str
    status: str
    routing: Routing | None = None
    confidence: float | None = None
    scores: Scorecard | None = None
    risk: Literal["none", "soft", "hard"] | None = None
    exception_codes: list[ExceptionCode] = Field(default_factory=list)
    primary_exception: ExceptionCode | None = None
    exceptions: list[ExceptionItem] = Field(default_factory=list)
    resolutions: list[dict] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    match: ThreeWayMatch | None = None
    email_draft: EmailDraft | None = None
    extractions: list[dict] = Field(default_factory=list)
    awaiting_approval: bool
    approval: ApprovalRecord | None = None


class RunSummary(BaseModel):
    id: str
    label: str | None = None
    status: str
    routing: Routing | None = None
    confidence: float | None = None
    exception_codes: list[ExceptionCode] = Field(default_factory=list)
    primary_exception: ExceptionCode | None = None
    awaiting_approval: bool
    po_number: str | None = None
    invoice_number: str | None = None
    vendor_name: str | None = None
    invoice_total: Decimal | None = None
    currency: str | None = None
    file_count: int = 0
    file_ids: list[str] = Field(default_factory=list)
    source_names: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


class RunList(BaseModel):
    runs: list[RunSummary]


class DraftUpdate(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
