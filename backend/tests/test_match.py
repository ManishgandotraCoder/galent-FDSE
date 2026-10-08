from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.pipeline.match import assess, three_way_match
from app.pipeline.validate import issues_for_extraction
from app.schemas.documents import LineItem, Party
from tests.helpers import extraction, goods_receipt, invoice, purchase_order


def test_schema_rejects_negative_quantity_and_keeps_unicode_names():
    with pytest.raises(ValidationError):
        LineItem(description="bolt", quantity=Decimal("-1"))
    vendor = Party(name="टाटा स्टील")
    assert vendor.name == "टाटा स्टील"


def test_matching_set_auto_clears():
    documents = [
        extraction(purchase_order(), file_id="po"),
        extraction(invoice(), file_id="inv"),
        extraction(goods_receipt(), file_id="grn"),
    ]
    matched = three_way_match(documents)
    issues = [issue for item in documents for issue in issues_for_extraction(item)]
    result = assess(documents, matched, issues, auto_clear=0.85, flag=0.55)

    assert matched.status == "matched"
    assert matched.exceptions == []
    assert result.routing == "auto_clear"
    assert result.exception_codes == []
    assert invoice().currency == "INR"


def test_small_total_difference_stays_inside_tolerance():
    documents = [
        extraction(purchase_order(total="1000"), file_id="po"),
        extraction(invoice(total="1004"), file_id="inv"),
        extraction(goods_receipt(), file_id="grn"),
    ]
    assert three_way_match(documents).exceptions == []


def test_wrong_total_vendor_price_and_partial_delivery():
    wrong_total = three_way_match(
        [
            extraction(purchase_order(), file_id="po"),
            extraction(invoice(total="1200"), file_id="inv"),
            extraction(goods_receipt(), file_id="grn"),
        ]
    )
    assert "total_mismatch" in wrong_total.exceptions

    wrong_vendor = three_way_match(
        [
            extraction(purchase_order(total=None), file_id="po"),
            extraction(invoice(vendor="JSW Steel", total=None), file_id="inv"),
            extraction(goods_receipt(total=None), file_id="grn"),
        ]
    )
    assert wrong_vendor.exceptions == ["vendor_mismatch"]

    partial = three_way_match(
        [
            extraction(purchase_order(total=None), file_id="po"),
            extraction(invoice(quantity="6", total=None), file_id="inv"),
            extraction(goods_receipt(quantity="6", total=None), file_id="grn"),
        ]
    )
    assert partial.exceptions == ["partial_delivery"]

    price = three_way_match(
        [
            extraction(purchase_order(total=None), file_id="po"),
            extraction(invoice(unit_price="140", total=None), file_id="inv"),
            extraction(goods_receipt(total=None), file_id="grn"),
        ]
    )
    assert price.exceptions == ["price_mismatch"]


def test_duplicate_invoice_and_missing_document_reject():
    duplicate = three_way_match(
        [
            extraction(purchase_order(), file_id="po"),
            extraction(invoice(number="INV-55"), file_id="inv-1"),
            extraction(invoice(number="INV-55"), file_id="inv-2"),
            extraction(goods_receipt(), file_id="grn"),
        ]
    )
    assert duplicate.exceptions == ["duplicate_invoice"]
    assert duplicate.po_total == Decimal("1000")
    assert duplicate.invoice_total == Decimal("1000")
    dup_docs = [
        extraction(purchase_order(total=None), confidence=0.99, file_id="po"),
        extraction(invoice(number="INV-55", total=None), confidence=0.99, file_id="inv-1"),
        extraction(invoice(number="INV-55", total=None), confidence=0.99, file_id="inv-2"),
        extraction(goods_receipt(total=None), confidence=0.99, file_id="grn"),
    ]
    routed = assess(dup_docs, duplicate, [], auto_clear=0.95, flag=0.70)
    assert routed.routing == "reject"
    assert routed.confidence == 0.99

    missing = three_way_match([extraction(invoice(), file_id="inv")])
    assert missing.status == "incomplete"
    assert missing.exceptions == ["missing_document"]

    failed = three_way_match([])
    result = assess([], failed, [], auto_clear=0.85, flag=0.55)
    assert result.routing == "reject"
    assert result.primary_exception == "extraction_failed"


def test_currency_disagreement_is_flagged_even_when_amounts_match():
    bill = invoice(total=None).model_copy(update={"currency": "USD"})
    matched = three_way_match(
        [
            extraction(purchase_order(total=None), file_id="po"),
            extraction(bill, file_id="inv"),
            extraction(goods_receipt(total=None), file_id="grn"),
        ]
    )
    assert "currency_mismatch" in matched.exceptions
    currency = next(check for check in matched.checks if check.label == "Currency agrees")
    assert currency.passed is False


def test_header_total_disagrees_with_line_items():
    bill = invoice(total="50")
    issues = issues_for_extraction(extraction(bill, file_id="inv"))
    assert [issue.code for issue in issues] == ["total_mismatch"]


def test_gstin_normalizes_a_legal_form_and_a_conflict_does_not():
    po = purchase_order(vendor="Acme Pvt Ltd").model_copy(
        update={"vendor": purchase_order(vendor="Acme Pvt Ltd").vendor.model_copy(update={"tax_id": "27AABCA9988A1Z1"})}
    )
    same_tax = invoice(vendor="ACME Private Limited").model_copy(
        update={"vendor": invoice(vendor="ACME Private Limited").vendor.model_copy(update={"tax_id": "27AABCA9988A1Z1"})}
    )
    receipt = goods_receipt(vendor="Acme Pvt Ltd").model_copy(
        update={"vendor": goods_receipt(vendor="Acme Pvt Ltd").vendor.model_copy(update={"tax_id": "27AABCA9988A1Z1"})}
    )
    normalized = [
        extraction(po, confidence=0.99, file_id="po"),
        extraction(same_tax, confidence=0.99, file_id="inv"),
        extraction(receipt, confidence=0.99, file_id="grn"),
    ]
    matched = three_way_match(normalized)
    result = assess(normalized, matched, [], auto_clear=0.95, flag=0.70)
    assert matched.exceptions == []
    assert result.routing == "auto_clear"
    assert any(rule.rule == "vendor" and rule.status == "WARN" for rule in matched.rules)

    conflict = same_tax.model_copy(
        update={"vendor": same_tax.vendor.model_copy(update={"tax_id": "29AADCD5566H1Z7", "name": "Deccan Hydraulics"})}
    )
    blocked = three_way_match(
        [
            extraction(po, confidence=0.99, file_id="po"),
            extraction(conflict, confidence=0.99, file_id="inv"),
            extraction(receipt, confidence=0.99, file_id="grn"),
        ]
    )
    routed = assess(
        [
            extraction(po, confidence=0.99, file_id="po"),
            extraction(conflict, confidence=0.99, file_id="inv"),
            extraction(receipt, confidence=0.99, file_id="grn"),
        ],
        blocked,
        [],
        auto_clear=0.95,
        flag=0.70,
    )
    assert blocked.exceptions == ["vendor_mismatch"]
    assert routed.routing == "flag"
    assert routed.confidence == 0.99


def test_duplicate_levels_and_a_perfect_read_cannot_clear_a_price_difference():
    po = purchase_order(total=None)
    first = invoice(number="INV-55", total=None)
    other_vendor = invoice(number="INV-55", vendor="Other Metals", total="10")
    suspicious = three_way_match(
        [
            extraction(po, file_id="po"),
            extraction(first, file_id="inv-1"),
            extraction(other_vendor, file_id="inv-2"),
            extraction(goods_receipt(total=None), file_id="grn"),
        ]
    )
    assert suspicious.exceptions == ["potential_duplicate"]
    flagged = assess(
        [extraction(po, confidence=0.99, file_id="po"), extraction(first, confidence=0.99, file_id="inv")],
        suspicious,
        [],
        auto_clear=0.95,
        flag=0.70,
    )
    assert flagged.routing == "flag"

    resubmitted = invoice(number="INV-55", po_number="PO-2000", total=None)
    resubmission = three_way_match(
        [
            extraction(po, file_id="po"),
            extraction(first, file_id="inv-1"),
            extraction(resubmitted, file_id="inv-2"),
            extraction(goods_receipt(total=None), file_id="grn"),
        ]
    )
    assert resubmission.exceptions == ["resubmission"]

    priced = three_way_match(
        [
            extraction(purchase_order(total=None), confidence=0.99, file_id="po"),
            extraction(invoice(unit_price="140", total=None), confidence=0.99, file_id="inv"),
            extraction(goods_receipt(total=None), confidence=0.99, file_id="grn"),
        ]
    )
    reviewed = assess(
        [
            extraction(purchase_order(total=None), confidence=0.99, file_id="po"),
            extraction(invoice(unit_price="140", total=None), confidence=0.99, file_id="inv"),
            extraction(goods_receipt(total=None), confidence=0.99, file_id="grn"),
        ],
        priced,
        [],
        auto_clear=0.95,
        flag=0.70,
    )
    assert priced.exceptions == ["price_mismatch"]
    assert reviewed.routing == "flag"
    assert reviewed.scores.extraction == 0.99
    assert reviewed.scores.routing_score < 0.95
    failed = next(rule for rule in priced.rules if rule.rule == "unit_price")
    assert failed.status == "FAIL"
    assert failed.expected == "100.00"
    assert failed.actual == "140.00"


def test_medium_confidence_is_flagged_and_low_confidence_is_rejected():
    documents = [
        extraction(purchase_order(), confidence=0.7, file_id="po"),
        extraction(invoice(), confidence=0.7, file_id="inv"),
        extraction(goods_receipt(), confidence=0.7, file_id="grn"),
    ]
    matched = three_way_match(documents)
    flagged = assess(documents, matched, [], auto_clear=0.85, flag=0.55)
    assert flagged.routing == "flag"
    assert flagged.primary_exception == "low_confidence"

    low = [
        extraction(document.document, confidence=0.4, file_id=document.file_id) for document in documents
    ]
    rejected = assess(low, matched, [], auto_clear=0.85, flag=0.55)
    assert rejected.routing == "reject"
