"""Synthetic cases built from the clean Apex packet.

The labelled files show that the reader works on this layout. They are
too few to say how the router behaves. These variants change one fact at a
time: a digit, a missing document, a GSTIN, a duplicate, a weak read. The
expected routing is written from the rule, not copied from the model output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.config import BACKEND_ROOT, get_settings
from app.eval.metrics import exception_counts, ratio, routing_rates
from app.pipeline.match import assess, three_way_match
from app.pipeline.validate import issues_for_extraction
from app.schemas.documents import Document, Extraction, GoodsReceipt, Invoice, PurchaseOrder

SAMPLE = BACKEND_ROOT / "sample_data" / "ground_truth.json"
MODELS = {
    "purchase_order": PurchaseOrder,
    "invoice": Invoice,
    "goods_receipt": GoodsReceipt,
}


@dataclass
class Variant:
    case_id: str
    kind: str
    extractions: list[Extraction]
    expected_exceptions: list[str]
    expected_routing: str


def score_variants() -> dict:
    settings = get_settings()
    cases = build_cases()
    exception_pairs: list[tuple[list[str], list[str]]] = []
    routing_pairs: list[tuple[str, str]] = []
    for case in cases:
        issues = [issue for item in case.extractions for issue in issues_for_extraction(item)]
        matched = three_way_match(case.extractions)
        result = assess(
            case.extractions,
            matched,
            issues,
            auto_clear=settings.auto_clear_confidence,
            flag=settings.flag_confidence,
        )
        exception_pairs.append((list(case.expected_exceptions), list(matched.exceptions)))
        routing_pairs.append((case.expected_routing, result.routing))
    true_positive, false_positive, false_negative = exception_counts(exception_pairs)
    report = routing_rates(routing_pairs)
    report.update(
        {
            "exception_precision": ratio(true_positive, true_positive + false_positive),
            "exception_recall": ratio(true_positive, true_positive + false_negative),
            "kinds": sorted({case.kind for case in cases}),
        }
    )
    return report


def build_cases() -> list[Variant]:
    base = _apex()
    cases: list[Variant] = []

    for confidence, completeness, routing in (
        (0.99, 1.0, "auto_clear"),
        (0.97, 1.0, "auto_clear"),
        (0.95, 1.0, "auto_clear"),
        (0.94, 1.0, "flag"),
        (0.85, 1.0, "flag"),
        (0.80, 1.0, "flag"),
        (0.70, 1.0, "flag"),
        (0.69, 1.0, "reject"),
        (0.42, 1.0, "reject"),
        (0.10, 1.0, "reject"),
        (0.99, 0.85, "flag"),
        (0.99, 0.70, "flag"),
        (0.99, 0.50, "reject"),
        (0.99, 0.20, "reject"),
    ):
        cases.append(
            _case(
                f"signal-{confidence}-{completeness}",
                "read_quality",
                base,
                confidence=confidence,
                completeness=completeness,
                expected_exceptions=[],
                expected_routing=routing,
            )
        )

    for name, drop in (("missing-po", 0), ("missing-invoice", 1), ("missing-grn", 2)):
        kept = [doc for index, doc in enumerate(base) if index != drop]
        cases.append(
            _case(name, "missing_document", kept, expected_exceptions=["missing_document"], expected_routing="reject")
        )

    for code in ("USD", "EUR", "GBP", "JPY"):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"currency": code})
        cases.append(
            _case(
                f"currency-{code}",
                "currency_mismatch",
                [po, inv, grn],
                expected_exceptions=["currency_mismatch"],
                expected_routing="flag",
            )
        )

    po_price = base[0].line_items[0].unit_price or Decimal("0")
    for delta in (Decimal("0.02"), Decimal("1"), Decimal("5"), Decimal("10"), Decimal("25"), Decimal("100"), Decimal("500"), Decimal("1000")):
        po, inv, grn = _clone(base)
        inv = _set_price(inv, po_price + delta)
        cases.append(
            _case(
                f"price-{delta}",
                "price_mismatch",
                [po, inv, grn],
                expected_exceptions=["price_mismatch"],
                expected_routing="flag",
                confidence=0.99,
            )
        )

    for quantity in ("1", "2", "7", "15", "39", "41", "80", "100"):
        po, inv, grn = _clone(base)
        inv = _set_qty(inv, quantity)
        cases.append(
            _case(
                f"qty-invoice-{quantity}",
                "quantity_mismatch",
                [po, inv, grn],
                expected_exceptions=["quantity_mismatch"],
                expected_routing="flag",
            )
        )

    for quantity in ("41", "45", "50", "60", "80", "120"):
        po, inv, grn = _clone(base)
        grn = _set_qty(grn, quantity)
        cases.append(
            _case(
                f"qty-over-{quantity}",
                "quantity_mismatch",
                [po, inv, grn],
                expected_exceptions=["quantity_mismatch"],
                expected_routing="flag",
            )
        )

    for quantity in ("1", "10", "20", "30", "39"):
        po, inv, grn = _clone(base)
        grn = _set_qty(grn, quantity)
        cases.append(
            _case(
                f"qty-received-{quantity}",
                "partial_delivery",
                [po, inv, grn],
                expected_exceptions=["quantity_mismatch", "partial_delivery"],
                expected_routing="flag",
            )
        )

    for bump in (Decimal("700"), Decimal("1000"), Decimal("5000"), Decimal("10000"), Decimal("-5000"), Decimal("25000"), Decimal("1234"), Decimal("900")):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"total": (inv.total or Decimal("0")) + bump})
        cases.append(
            _case(
                f"total-{bump}",
                "total_mismatch",
                [po, inv, grn],
                expected_exceptions=["total_mismatch"],
                expected_routing="flag",
            )
        )

    for bump in (Decimal("1"), Decimal("10"), Decimal("100"), Decimal("-1")):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"total": (inv.total or Decimal("0")) + bump})
        cases.append(
            _case(
                f"total-within-{bump}",
                "within_tolerance",
                [po, inv, grn],
                expected_exceptions=[],
                expected_routing="auto_clear",
            )
        )

    for factor in (Decimal("0"), Decimal("2"), Decimal("0.5"), Decimal("1.5")):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"tax": (inv.tax or Decimal("0")) * factor})
        cases.append(
            _case(
                f"tax-{factor}",
                "tax_mismatch",
                [po, inv, grn],
                expected_exceptions=["tax_mismatch"],
                expected_routing="flag",
            )
        )

    for suffix in ("Private Limited", "Pvt. Ltd.", "PVT LTD", "Limited"):
        po, inv, grn = _clone(base)
        inv = _rename(inv, f"Apex Steel Traders {suffix}")
        cases.append(
            _case(
                f"legal-form-{suffix}",
                "gstin_normalization",
                [po, inv, grn],
                expected_exceptions=[],
                expected_routing="auto_clear",
            )
        )

    for name, tax_id in (
        ("Deccan Hydraulics", "29AADCD5566H1Z7"),
        ("Other Metals Pvt Ltd", "24AAAAA1111A1Z1"),
        ("Western Hydraulics Ltd", "27AABCW4455C1Z2"),
        ("Gupta Steels", "09AABCG1234A1Z5"),
    ):
        po, inv, grn = _clone(base)
        inv = _rename(inv, name, tax_id)
        cases.append(
            _case(
                f"vendor-{name}",
                "vendor_mismatch",
                [po, inv, grn],
                expected_exceptions=["vendor_mismatch"],
                expected_routing="flag",
            )
        )

    po, inv, grn = _clone(base)
    po, inv, grn = _clear_tax(po), _clear_tax(inv), _clear_tax(grn)
    inv = _rename(inv, "Apex Steel Trader")
    cases.append(
        _case(
            "vendor-fuzzy",
            "vendor_mismatch",
            [po, inv, grn],
            expected_exceptions=["vendor_mismatch"],
            expected_routing="flag",
        )
    )

    po, inv, grn = _clone(base)
    cases.append(
        _case(
            "duplicate-exact",
            "duplicate_invoice",
            [po, inv, grn, inv.model_copy(deep=True)],
            expected_exceptions=["duplicate_invoice"],
            expected_routing="reject",
            confidence=0.99,
        )
    )
    po, inv, grn = _clone(base)
    dated = inv.model_copy(deep=True, update={"document_date": date(2026, 9, 11)})
    cases.append(
        _case(
            "duplicate-exact-different-date",
            "duplicate_invoice",
            [po, inv, grn, dated],
            expected_exceptions=["duplicate_invoice"],
            expected_routing="reject",
        )
    )
    po, inv, grn = _clone(base)
    suspicious = inv.model_copy(
        deep=True,
        update={
            "vendor": inv.vendor.model_copy(update={"name": "Other Metals", "tax_id": "29AAAAA0000A1Z1"}),
            "total": Decimal("1.00"),
        },
    )
    cases.append(
        _case(
            "duplicate-suspicious",
            "potential_duplicate",
            [po, inv, grn, suspicious],
            expected_exceptions=["potential_duplicate"],
            expected_routing="flag",
        )
    )
    po, inv, grn = _clone(base)
    resubmitted = inv.model_copy(deep=True, update={"po_number": "PO-99999"})
    cases.append(
        _case(
            "duplicate-resubmission",
            "resubmission",
            [po, inv, grn, resubmitted],
            expected_exceptions=["resubmission"],
            expected_routing="flag",
        )
    )

    for day in range(1, 9):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"document_date": date(2026, 1, day)})
        cases.append(
            _case(
                f"date-{day}",
                "date_variation",
                [po, inv, grn],
                expected_exceptions=[],
                expected_routing="auto_clear",
            )
        )

    po, inv, grn = _clone(base)
    hindi = "टाटा स्टील"
    cases.append(
        _case(
            "hindi-same-vendor",
            "hindi",
            [_rename(po, hindi), _rename(inv, hindi), _rename(grn, hindi)],
            expected_exceptions=[],
            expected_routing="auto_clear",
        )
    )
    po, inv, grn = _clone(base)
    cases.append(
        _case(
            "mixed-language-same-vendor",
            "mixed_language",
            [_rename(po, "Apex Steel ट्रेडर्स"), _rename(inv, "Apex Steel ट्रेडर्स"), _rename(grn, "Apex Steel ट्रेडर्स")],
            expected_exceptions=[],
            expected_routing="auto_clear",
        )
    )

    for cited in ("PO-1", "PO-999", "PO-24019", "PO-00000", "PO-24018-X"):
        po, inv, grn = _clone(base)
        inv = inv.model_copy(update={"po_number": cited})
        cases.append(
            _case(
                f"po-{cited}",
                "po_mismatch",
                [po, inv, grn],
                expected_exceptions=["po_mismatch"],
                expected_routing="flag",
            )
        )

    second_price = base[1].line_items[1].unit_price or Decimal("0")
    for delta in (Decimal("0.05"), Decimal("2"), Decimal("15"), Decimal("40")):
        po, inv, grn = _clone(base)
        inv = _set_price(inv, second_price + delta, index=1)
        cases.append(
            _case(
                f"price-line2-{delta}",
                "price_mismatch",
                [po, inv, grn],
                expected_exceptions=["price_mismatch"],
                expected_routing="flag",
            )
        )

    for label, confidence, completeness, routing in (
        ("rotated", 0.40, 0.40, "reject"),
        ("low-scan", 0.55, 0.90, "reject"),
        ("photo-cap", 0.90, 1.0, "flag"),
        ("model-fallback", 0.85, 1.0, "flag"),
    ):
        cases.append(
            _case(
                label,
                "low_quality",
                base,
                confidence=confidence,
                completeness=completeness,
                expected_exceptions=[],
                expected_routing=routing,
            )
        )
    return cases


def _case(
    case_id: str,
    kind: str,
    documents: list[Document],
    *,
    expected_exceptions: list[str],
    expected_routing: str,
    confidence: float = 0.99,
    completeness: float = 1.0,
) -> Variant:
    extractions = [
        Extraction(
            file_id=f"{case_id}-{index}",
            source_name=f"{case_id}-{document.document_type}",
            document_type=document.document_type,
            document=document,
            confidence=confidence,
            completeness=completeness,
        )
        for index, document in enumerate(documents)
    ]
    return Variant(case_id, kind, extractions, expected_exceptions, expected_routing)


def _apex() -> list[Document]:
    pack = json.loads(SAMPLE.read_text(encoding="utf-8"))
    by_file = {item["file"]: item for item in pack["documents"]}
    bundle = next(item for item in pack["bundles"] if item["id"] == "apex-steel-clean")
    documents: list[Document] = []
    for name in bundle["files"]:
        raw = by_file[name]["document"]
        documents.append(MODELS[raw["document_type"]].model_validate(raw))
    return documents


def _clone(documents: list[Document]) -> tuple[Document, Document, Document]:
    copied = [document.model_copy(deep=True) for document in documents]
    return copied[0], copied[1], copied[2]


def _rename(document: Document, name: str, tax_id: str | None = None) -> Document:
    vendor = document.vendor.model_copy(update={"name": name})
    if tax_id is not None:
        vendor = vendor.model_copy(update={"tax_id": tax_id})
    return document.model_copy(update={"vendor": vendor})


def _clear_tax(document: Document) -> Document:
    return document.model_copy(update={"vendor": document.vendor.model_copy(update={"tax_id": None})})


def _set_qty(document: Document, quantity: str) -> Document:
    lines = [line.model_copy(deep=True) for line in document.line_items]
    lines[0] = lines[0].model_copy(update={"quantity": Decimal(quantity)})
    return document.model_copy(update={"line_items": lines})


def _set_price(document: Document, price: Decimal, index: int = 0) -> Document:
    lines = [line.model_copy(deep=True) for line in document.line_items]
    lines[index] = lines[index].model_copy(update={"unit_price": price})
    return document.model_copy(update={"line_items": lines})
