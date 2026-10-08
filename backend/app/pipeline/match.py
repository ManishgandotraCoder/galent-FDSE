from datetime import date
from decimal import Decimal

from app.pipeline.scores import case_scores
from app.pipeline.vendor import raw_name, vendors_agree
from app.schemas.documents import Document, Extraction, LineItem, Party
from app.schemas.pipeline import (
    HARD_EXCEPTIONS,
    SEVERITY,
    VENDOR_EMAIL_CODES,
    Assessment,
    EmailDraft,
    ExceptionCode,
    ExceptionItem,
    LineComparison,
    MatchCheck,
    Routing,
    RuleResult,
    Scorecard,
    ThreeWayMatch,
    ValidationIssue,
)

PRICE_TOLERANCE = Decimal("0.01")

_DEFAULT_MESSAGE: dict[ExceptionCode, str] = {
    "extraction_failed": "A document could not be read into the schema.",
    "missing_document": "A purchase order, invoice, and goods receipt are all required.",
    "duplicate_invoice": "Same invoice number, vendor, amount, and purchase order. This is an exact duplicate.",
    "potential_duplicate": "The invoice number is reused, but the vendor or the amount is different.",
    "resubmission": "The same vendor reused an invoice number against a different purchase order.",
    "po_mismatch": "The invoice or goods receipt cites a purchase order that is not in this set.",
    "vendor_mismatch": "The vendor does not match the purchase order.",
    "currency_mismatch": "The purchase order, invoice, and goods receipt are not in the same currency.",
    "total_mismatch": "The invoice total does not match the purchase order.",
    "tax_mismatch": "The invoice tax does not match the purchase order.",
    "price_mismatch": "An invoice unit price does not match the purchase order.",
    "quantity_mismatch": "An invoice quantity does not match the quantity received.",
    "partial_delivery": "The goods receipt is short of the quantity ordered.",
    "low_confidence": "The routing score is below the line for an unattended clear.",
}


def three_way_match(extractions: list[Extraction]) -> ThreeWayMatch:
    documents = [item.document for item in extractions if item.document is not None]
    if not documents:
        failed: list[ExceptionCode] = ["extraction_failed"]
        rules = [
            _rule(
                "extraction",
                "FAIL",
                "HIGH",
                "No structured purchase order, invoice, or goods receipt was extracted.",
                code="extraction_failed",
            )
        ]
        return ThreeWayMatch(
            status="incomplete",
            exceptions=failed,
            checks=_checks([], failed),
            rules=rules,
            summary="No structured purchase order, invoice, or goods receipt was extracted.",
        )

    rules = _duplicate_rules([doc for doc in documents if doc.document_type == "invoice"])
    comparable = _one_per_invoice_number(documents)
    groups: dict[str, list[Document]] = {}
    for document in comparable:
        groups.setdefault(_group_key(document), []).append(document)

    lines: list[LineComparison] = []
    header = _header_from(comparable)
    for group in groups.values():
        rules.extend(_compare_group(group, lines))
    rules.extend(_po_rules(comparable))
    rules.extend(_presence_rule(comparable))

    ordered = _ordered([rule.code for rule in rules if rule.status == "FAIL" and rule.code])
    vendor_name, currency, po_total, invoice_total, grn_total = _display(comparable)
    return ThreeWayMatch(
        status=_status(ordered),
        po_number=header[0],
        invoice_number=header[1],
        grn_number=header[2],
        vendor_name=vendor_name,
        currency=currency,
        po_total=po_total,
        invoice_total=invoice_total,
        grn_total=grn_total,
        exceptions=ordered,
        lines=lines,
        checks=_checks(documents, ordered),
        rules=rules,
        summary=_summary(ordered, header, lines),
    )


def assess(
    extractions: list[Extraction],
    match: ThreeWayMatch,
    issues: list[ValidationIssue],
    *,
    auto_clear: float,
    flag: float,
) -> Assessment:
    scores = case_scores(extractions, issues, match.rules)
    codes: list[ExceptionCode] = [issue.code for issue in issues]
    codes.extend(match.exceptions)
    business = [code for code in _ordered(codes) if code != "low_confidence"]
    if not business and scores.routing_score < auto_clear:
        business = _ordered([*business, "low_confidence"])
    routing = decide_routing(scores.routing_score, business, auto_clear=auto_clear, flag=flag)
    risk = _risk(business, routing)
    return Assessment(
        exception_codes=business,
        primary_exception=business[0] if business else None,
        confidence=scores.extraction,
        scores=scores,
        risk=risk,
        routing=routing,
        exceptions=describe_exceptions(business, match, issues, scores=scores, auto_clear=auto_clear),
    )


def describe_exceptions(
    codes: list[ExceptionCode],
    match: ThreeWayMatch | None,
    issues: list[ValidationIssue],
    *,
    scores=None,
    auto_clear: float = 0.95,
) -> list[ExceptionItem]:
    notes = [note for line in (match.lines if match else []) for note in line.notes]
    items: list[ExceptionItem] = []
    for code in codes:
        message = _DEFAULT_MESSAGE[code]
        if code in {"quantity_mismatch", "partial_delivery", "price_mismatch"}:
            related = next((note for note in notes if _note_matches(code, note)), None)
            if related:
                message = related
        elif code == "total_mismatch":
            related = next((issue.message for issue in issues if issue.code == "total_mismatch"), None)
            if related:
                message = related
        elif code == "extraction_failed":
            related = next((issue.message for issue in issues if issue.code == "extraction_failed"), None)
            if related:
                message = related
        elif code == "low_confidence" and scores is not None:
            message = (
                f"Routing score {scores.routing_score:.2f} is below {auto_clear:.2f}. "
                f"Completeness {scores.completeness:.2f}, extraction {scores.extraction:.2f}, "
                f"validation {scores.validation:.2f}, match {scores.matching:.2f}."
            )
        elif match is not None:
            related = next((rule.reason for rule in match.rules if rule.code == code and rule.status == "FAIL"), None)
            if related:
                message = related
        medium = {"low_confidence", "potential_duplicate", "resubmission"}
        items.append(
            ExceptionItem(
                type=code,
                severity="medium" if code in medium else "high",
                message=message,
            )
        )
    return items


def _note_matches(code: ExceptionCode, note: str) -> bool:
    if code == "partial_delivery":
        return note.startswith("Received") and " of " in note or "No goods receipt" in note
    if code == "quantity_mismatch":
        return "Invoice quantity" in note or " against " in note
    if code == "price_mismatch":
        return note.startswith("Unit price")
    return False


def decide_routing(
    routing_score: float,
    codes: list[ExceptionCode],
    *,
    auto_clear: float,
    flag: float,
) -> Routing:
    """Exception type decides first. The score is used only when nothing failed."""
    business = [code for code in codes if code != "low_confidence"]
    if any(code in HARD_EXCEPTIONS for code in business):
        return "reject"
    if business:
        return "flag"
    if routing_score < flag:
        return "reject"
    if routing_score < auto_clear:
        return "flag"
    return "auto_clear"


def _risk(codes: list[ExceptionCode], routing: Routing) -> str:
    business = [code for code in codes if code != "low_confidence"]
    if any(code in HARD_EXCEPTIONS for code in business) or routing == "reject":
        return "hard"
    if business or routing == "flag":
        return "soft"
    return "none"


_ASK: dict[ExceptionCode, str] = {
    "partial_delivery": "Send a revised invoice for the quantity received, or confirm when the balance will arrive on this purchase order.",
    "quantity_mismatch": "Send a revised invoice whose quantity matches what was received.",
    "price_mismatch": "Send a revised invoice at the purchase-order price, or a written agreement for the different price.",
    "total_mismatch": "Send a corrected invoice whose total matches the lines and the purchase order.",
    "tax_mismatch": "Send a corrected invoice with the tax shown on the purchase order.",
    "vendor_mismatch": "The bill is not from the vendor on the purchase order. Confirm who should be paid, or send the invoice from that vendor.",
    "currency_mismatch": "Reissue the invoice in the currency of the purchase order.",
    "po_mismatch": "The invoice cites a purchase order that is not in this set. Quote the correct purchase-order number.",
    "duplicate_invoice": "This is the same invoice submitted twice. Do not pay it again unless you can show it is a different supply.",
    "potential_duplicate": "This invoice number was used before, but the vendor or the amount differs. Confirm it is a new bill before paying.",
    "resubmission": "The same vendor reused an invoice number on a different purchase order. Confirm this is a new supply.",
    "missing_document": "Wait for the missing document. A purchase order, an invoice, and a goods receipt are all required before payment.",
    "extraction_failed": "A file could not be read. Replace it with a clearer copy before this set can be matched.",
    "low_confidence": "Read the pages before clearing. The score is below the line for an unattended payment.",
}

_KIND = {
    "purchase_order": "Purchase order",
    "goods_receipt": "Goods receipt",
    "invoice": "Invoice",
}


def build_email(
    *,
    routing: Routing,
    primary: ExceptionCode | None,
    codes: list[ExceptionCode],
    match: ThreeWayMatch | None,
    confidence: float,
    extractions: list[Extraction] | None = None,
    scores: Scorecard | None = None,
    exceptions: list[ExceptionItem] | None = None,
) -> EmailDraft:
    vendor_mail = routing == "flag" and primary in VENDOR_EMAIL_CODES
    po_number = match.po_number if match and match.po_number else None
    invoice_number = match.invoice_number if match else None
    vendor = match.vendor_name if match and match.vendor_name else None
    reference = f"invoice {invoice_number}" if invoice_number else (f"purchase order {po_number}" if po_number else "this set")
    history = _history(extractions, match)
    disagreement = _disagreement(match, exceptions)
    ask = _ASK.get(primary or "", "Review the points below and decide whether this can be paid.")
    if vendor_mail:
        subject_bit = invoice_number or po_number or "this supply"
        return EmailDraft(
            to_role="vendor",
            subject=f"Please correct {subject_bit}",
            body=(
                f"Hello{(' ' + vendor) if vendor else ''},\n\n"
                f"Northwind Fabrication is holding {reference}"
                f"{f' against purchase order {po_number}' if po_number and invoice_number else ''}. "
                "This is not a payment advice. This note has not been sent.\n\n"
                f"{history}"
                f"{disagreement}"
                f"What we need from you\n{ask}\n\n"
                "Accounts payable\nNorthwind Fabrication\n"
            ),
        )
    held = _why_held(routing, primary, scores, confidence)
    return EmailDraft(
        to_role="approver",
        subject=f"Decision needed on {reference}",
        body=(
            "Hello,\n\n"
            f"{reference[:1].upper()}{reference[1:]} is waiting for a person. "
            "Nothing has been sent to the vendor.\n\n"
            f"{history}"
            f"{disagreement}"
            f"Why it is waiting\n{held}\n\n"
            f"What to decide\n{ask}\n"
        ),
    )


def _history(extractions: list[Extraction] | None, match: ThreeWayMatch | None) -> str:
    documents = [item.document for item in extractions or [] if item.document is not None]
    if not documents:
        if match is None or not any((match.po_number, match.invoice_number, match.grn_number)):
            return ""
        bits = []
        if match.vendor_name:
            bits.append(match.vendor_name)
        if match.po_number:
            bits.append(f"purchase order {match.po_number}")
        if match.invoice_number:
            bits.append(f"invoice {match.invoice_number}")
        if match.grn_number:
            bits.append(f"goods receipt {match.grn_number}")
        amounts = _amount_line(match)
        text = "We have " + ", ".join(bits) + "."
        if amounts:
            text = f"{text} {amounts}"
        return f"What we have on file\n{text}\n\n"
    kind_rank = {"purchase_order": 0, "goods_receipt": 1, "invoice": 2}
    ordered = sorted(
        documents,
        key=lambda doc: (
            doc.document_date is None,
            doc.document_date or date.min,
            kind_rank.get(doc.document_type, 9),
            doc.document_number,
        ),
    )
    lines = ["What we have on file"]
    for doc in ordered:
        when = doc.document_date.strftime("%d %b %Y") if doc.document_date else "Date not printed"
        kind = _KIND.get(doc.document_type, doc.document_type)
        cite = ""
        if doc.document_type != "purchase_order" and getattr(doc, "po_number", None):
            cite = f" against {doc.po_number}"
        money = _rupees(doc.total, doc.currency)
        amount = f" for {money}" if money else ""
        goods = _goods(doc)
        supply = f" — {goods}" if goods else ""
        received = ""
        if doc.document_type == "goods_receipt" and doc.received_by:
            received = f" Received by {doc.received_by}."
        lines.append(f"- {when}: {kind} {doc.document_number}{cite} from {doc.vendor.name}{amount}{supply}.{received}")
    amounts = _amount_line(match) if match else ""
    if amounts:
        lines.append(amounts)
    return "\n".join(lines) + "\n\n"


def _goods(document: Document) -> str:
    parts = []
    for line in document.line_items[:3]:
        unit = f" {line.unit}" if line.unit else ""
        parts.append(f"{_format_qty(line.quantity)}{unit} {line.description}")
    extra = len(document.line_items) - len(parts)
    if extra > 0:
        parts.append(f"{extra} more")
    return "; ".join(parts)


def _amount_line(match: ThreeWayMatch | None) -> str:
    if match is None:
        return ""
    parts = []
    for label, value in (
        ("purchase order", match.po_total),
        ("invoice", match.invoice_total),
        ("goods receipt", match.grn_total),
    ):
        money = _rupees(value, match.currency)
        if money:
            parts.append(f"{label} {money}")
    if not parts:
        return ""
    return "Header totals: " + ", ".join(parts) + "."


def _rupees(value: Decimal | None, currency: str | None) -> str | None:
    shown = _show(value)
    if shown is None:
        return None
    code = (currency or "INR").upper()
    if code == "INR":
        return f"Rs. {shown}"
    return f"{code} {shown}"


def _disagreement(match: ThreeWayMatch | None, exceptions: list[ExceptionItem] | None) -> str:
    messages = [item.message for item in exceptions or [] if item.type != "low_confidence"]
    if not messages and match is not None:
        messages = [rule.reason for rule in match.rules if rule.status == "FAIL" and rule.reason]
    if not messages:
        return ""
    lines = "\n".join(f"- {message}" for message in messages)
    return f"What does not agree\n{lines}\n\n"


def _why_held(
    routing: Routing,
    primary: ExceptionCode | None,
    scores: Scorecard | None,
    confidence: float,
) -> str:
    if routing == "reject":
        lead = "The case was rejected. It cannot be paid as submitted."
    elif primary == "low_confidence":
        lead = "Nothing in the match failed, but the read is too weak to clear on its own."
    else:
        lead = "The case was held for review. It was not auto-cleared."
    if scores is None:
        return f"{lead} Extraction confidence {confidence:.0%}."
    return (
        f"{lead} Routing score {scores.routing_score:.0%} "
        f"(completeness {scores.completeness:.0%}, extraction {scores.extraction:.0%}, "
        f"validation {scores.validation:.0%}, match {scores.matching:.0%})."
    )


def _rule(
    rule: str,
    status: str,
    severity: str,
    reason: str,
    *,
    expected: str | None = None,
    actual: str | None = None,
    code: ExceptionCode | None = None,
) -> RuleResult:
    return RuleResult(
        rule=rule,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        reason=reason,
        expected=expected,
        actual=actual,
        code=code if status == "FAIL" else None,
    )


def _duplicate_rules(invoices: list[Document]) -> list[RuleResult]:
    grouped: dict[str, list[Document]] = {}
    for document in invoices:
        grouped.setdefault(document.document_number.casefold(), []).append(document)
    rules: list[RuleResult] = []
    for number, group in grouped.items():
        if len(group) < 2:
            continue
        base, other = group[0], group[1]
        decision = vendors_agree(base.vendor, other.vendor)
        same_amount = _same_money(base.total, other.total)
        same_po = _group_key(base) == _group_key(other)
        same_date = base.document_date == other.document_date
        expected = f"{number}, {base.vendor.name}, {_show(base.total)}"
        actual = f"{number}, {other.vendor.name}, {_show(other.total)}"
        if decision.agreed and same_amount and same_po:
            date_note = " Invoice dates agree." if same_date else " Invoice dates differ."
            rules.append(
                _rule(
                    "invoice_number",
                    "FAIL",
                    "HIGH",
                    "Exact duplicate: invoice number, vendor, amount, and purchase order all agree." + date_note,
                    expected=expected,
                    actual=actual,
                    code="duplicate_invoice",
                )
            )
        elif decision.agreed and not same_po:
            rules.append(
                _rule(
                    "invoice_number",
                    "FAIL",
                    "MEDIUM",
                    "Potential resubmission: same invoice number and vendor, different purchase order.",
                    expected=base.po_number if base.document_type != "purchase_order" else base.document_number,
                    actual=other.po_number if other.document_type != "purchase_order" else other.document_number,
                    code="resubmission",
                )
            )
        else:
            rules.append(
                _rule(
                    "invoice_number",
                    "FAIL",
                    "MEDIUM",
                    "Suspicious reuse: same invoice number, but the vendor or the amount differs.",
                    expected=expected,
                    actual=actual,
                    code="potential_duplicate",
                )
            )
    if rules:
        return rules
    if invoices:
        return [_rule("invoice_number", "PASS", "LOW", "Invoice number is unique in this set.")]
    return [_rule("invoice_number", "PASS", "LOW", "No invoice number to compare.")]


def _po_rules(documents: list[Document]) -> list[RuleResult]:
    purchase_orders = [doc for doc in documents if doc.document_type == "purchase_order"]
    cited = [doc for doc in documents if doc.document_type != "purchase_order"]
    if not purchase_orders:
        return [_rule("po_number", "PASS", "LOW", "No purchase order in this set to compare.")]
    po_numbers = sorted({doc.document_number for doc in purchase_orders})
    rules: list[RuleResult] = []
    for document in cited:
        if _group_key(document) not in {_group_key(doc) for doc in purchase_orders}:
            rules.append(
                _rule(
                    "po_number",
                    "FAIL",
                    "HIGH",
                    "The document cites a purchase order that is not in this set.",
                    expected=", ".join(po_numbers),
                    actual=document.po_number,
                    code="po_mismatch",
                )
            )
    if rules:
        return rules
    shown = cited[0].po_number if cited else po_numbers[0]
    return [_rule("po_number", "PASS", "LOW", "Purchase order number agrees.", expected=po_numbers[0], actual=shown)]


def _presence_rule(documents: list[Document]) -> list[RuleResult]:
    types = {document.document_type for document in documents}
    missing = [
        label
        for label, kind in (
            ("purchase order", "purchase_order"),
            ("invoice", "invoice"),
            ("goods receipt", "goods_receipt"),
        )
        if kind not in types
    ]
    if missing:
        return [
            _rule(
                "documents_present",
                "FAIL",
                "HIGH",
                "A three-way match needs a purchase order, an invoice, and a goods receipt.",
                expected="purchase order, invoice, goods receipt",
                actual="missing " + ", ".join(missing),
                code="missing_document",
            )
        ]
    return [_rule("documents_present", "PASS", "LOW", "Purchase order, invoice, and goods receipt are all present.")]


def _compare_group(group: list[Document], lines: list[LineComparison]) -> list[RuleResult]:
    purchase_orders = [doc for doc in group if doc.document_type == "purchase_order"]
    invoices = [doc for doc in group if doc.document_type == "invoice"]
    receipts = [doc for doc in group if doc.document_type == "goods_receipt"]
    rules: list[RuleResult] = []
    rules.extend(_vendor_rules(purchase_orders, [*invoices, *receipts]))
    rules.extend(_currency_rules(group))
    rules.extend(_total_rule(purchase_orders, invoices))
    rules.extend(_tax_rule(purchase_orders, invoices))
    rules.extend(_compare_lines(purchase_orders, invoices, receipts, lines))
    return rules


def _vendor_rules(purchase_orders: list[Document], others: list[Document]) -> list[RuleResult]:
    if not purchase_orders or not others:
        return [_rule("vendor", "PASS", "LOW", "Vendor was not compared because a document is missing.")]
    po_vendor = purchase_orders[0].vendor
    warnings: list[RuleResult] = []
    for document in others:
        decision = vendors_agree(po_vendor, document.vendor)
        names_differ = raw_name(po_vendor.name) != raw_name(document.vendor.name)
        if decision.method == "gstin_conflict":
            return [
                _rule(
                    "vendor",
                    "FAIL",
                    "HIGH",
                    "GSTIN does not match the purchase order. The legal name cannot override a different tax id.",
                    expected=_vendor_label(po_vendor),
                    actual=_vendor_label(document.vendor),
                    code="vendor_mismatch",
                )
            ]
        if not decision.agreed:
            severity = "MEDIUM" if decision.method == "fuzzy" else "HIGH"
            reason = (
                "Vendor names are similar but the GSTIN does not confirm them."
                if decision.method == "fuzzy"
                else "Vendor name does not match the purchase order, and the GSTIN does not confirm them."
            )
            return [
                _rule(
                    "vendor",
                    "FAIL",
                    severity,
                    reason,
                    expected=_vendor_label(po_vendor),
                    actual=_vendor_label(document.vendor),
                    code="vendor_mismatch",
                )
            ]
        if names_differ:
            warnings.append(
                _rule(
                    "vendor",
                    "WARN",
                    "LOW",
                    "Same vendor. The GSTIN or the normalized legal name matches, so the wording difference is not a mismatch.",
                    expected=po_vendor.name,
                    actual=document.vendor.name,
                )
            )
    if warnings:
        return [warnings[0]]
    return [
        _rule(
            "vendor",
            "PASS",
            "LOW",
            "Vendor matches the purchase order.",
            expected=po_vendor.name,
            actual=others[0].vendor.name,
        )
    ]


def _currency_rules(group: list[Document]) -> list[RuleResult]:
    currencies = sorted({document.currency.upper() for document in group if document.currency})
    if len(currencies) > 1:
        return [
            _rule(
                "currency",
                "FAIL",
                "HIGH",
                "Currency does not agree across the documents.",
                expected=currencies[0],
                actual=", ".join(currencies),
                code="currency_mismatch",
            )
        ]
    shown = currencies[0] if currencies else None
    return [_rule("currency", "PASS", "LOW", "Currency agrees.", expected=shown, actual=shown)]


def _total_rule(purchase_orders: list[Document], invoices: list[Document]) -> list[RuleResult]:
    po_total = _combined_total(purchase_orders)
    invoice_total = _combined_total(invoices)
    if po_total is None or invoice_total is None:
        return [_rule("total", "PASS", "LOW", "Total was not on both documents, so it was not compared.")]
    if not _totals_close(po_total, invoice_total):
        return [
            _rule(
                "total",
                "FAIL",
                "HIGH",
                "Invoice total does not match the purchase order.",
                expected=_show(po_total),
                actual=_show(invoice_total),
                code="total_mismatch",
            )
        ]
    return [
        _rule(
            "total",
            "PASS",
            "LOW",
            "Invoice total matches the purchase order.",
            expected=_show(po_total),
            actual=_show(invoice_total),
        )
    ]


def _tax_rule(purchase_orders: list[Document], invoices: list[Document]) -> list[RuleResult]:
    po_tax = _combined_tax(purchase_orders)
    invoice_tax = _combined_tax(invoices)
    if po_tax is None or invoice_tax is None:
        return [_rule("tax", "PASS", "LOW", "Tax was not on both documents, so it was not compared.")]
    if not _totals_close(po_tax, invoice_tax):
        return [
            _rule(
                "tax",
                "FAIL",
                "HIGH",
                "Invoice tax does not match the purchase order.",
                expected=_show(po_tax),
                actual=_show(invoice_tax),
                code="tax_mismatch",
            )
        ]
    return [
        _rule("tax", "PASS", "LOW", "Tax matches the purchase order.", expected=_show(po_tax), actual=_show(invoice_tax))
    ]


def _compare_lines(
    purchase_orders: list[Document],
    invoices: list[Document],
    receipts: list[Document],
    lines: list[LineComparison],
) -> list[RuleResult]:
    po_lines = _index_lines(purchase_orders)
    invoice_lines = _index_lines(invoices)
    receipt_lines = _index_lines(receipts)
    rules: list[RuleResult] = []
    if not po_lines and not invoice_lines and not receipt_lines:
        return [
            _rule("received_quantity", "PASS", "LOW", "No lines to compare."),
            _rule("quantity", "PASS", "LOW", "No lines to compare."),
            _rule("unit_price", "PASS", "LOW", "No lines to compare."),
        ]

    received_fail: RuleResult | None = None
    quantity_fail: RuleResult | None = None
    price_fail: RuleResult | None = None
    for key in dict.fromkeys([*po_lines, *invoice_lines, *receipt_lines]):
        po_group = po_lines.get(key, [])
        invoice_group = invoice_lines.get(key, [])
        receipt_group = receipt_lines.get(key, [])
        ordered = _quantity(po_group)
        invoiced = _quantity(invoice_group)
        received = _quantity(receipt_group)
        po_price = _unit_price(po_group)
        invoice_price = _unit_price(invoice_group)
        notes: list[str] = []

        if ordered is not None and received is not None and received < ordered:
            note = f"Received {_format_qty(received)} of {_format_qty(ordered)} ordered."
            notes.append(note)
            received_fail = received_fail or _rule(
                "received_quantity",
                "FAIL",
                "HIGH",
                note,
                expected=_format_qty(ordered),
                actual=_format_qty(received),
                code="partial_delivery",
            )
        elif ordered is not None and received is not None and received > ordered:
            note = f"Received {_format_qty(received)} against {_format_qty(ordered)} ordered."
            notes.append(note)
            received_fail = received_fail or _rule(
                "received_quantity",
                "FAIL",
                "HIGH",
                note,
                expected=_format_qty(ordered),
                actual=_format_qty(received),
                code="quantity_mismatch",
            )
        elif ordered is not None and received is None and receipts:
            note = "No goods receipt line for this item."
            notes.append(note)
            received_fail = received_fail or _rule(
                "received_quantity",
                "FAIL",
                "HIGH",
                note,
                expected=_format_qty(ordered),
                actual=None,
                code="partial_delivery",
            )

        if invoiced is not None and received is not None and invoiced != received:
            note = f"Invoice quantity {_format_qty(invoiced)} does not match received quantity {_format_qty(received)}."
            notes.append(note)
            quantity_fail = quantity_fail or _rule(
                "quantity",
                "FAIL",
                "HIGH",
                note,
                expected=_format_qty(received),
                actual=_format_qty(invoiced),
                code="quantity_mismatch",
            )
        elif invoiced is not None and ordered is not None and received is None and invoiced != ordered:
            note = f"Invoice quantity {_format_qty(invoiced)} does not match ordered quantity {_format_qty(ordered)}."
            notes.append(note)
            quantity_fail = quantity_fail or _rule(
                "quantity",
                "FAIL",
                "HIGH",
                note,
                expected=_format_qty(ordered),
                actual=_format_qty(invoiced),
                code="quantity_mismatch",
            )

        if po_price is not None and invoice_price is not None and abs(po_price - invoice_price) > PRICE_TOLERANCE:
            note = f"Unit price {_format_money(invoice_price)} does not match PO price {_format_money(po_price)}."
            notes.append(note)
            price_fail = price_fail or _rule(
                "unit_price",
                "FAIL",
                "HIGH",
                note,
                expected=_format_money(po_price),
                actual=_format_money(invoice_price),
                code="price_mismatch",
            )

        description = next(
            (line.description for line in [*po_group, *invoice_group, *receipt_group] if line.description),
            key,
        )
        lines.append(
            LineComparison(
                key=key,
                description=description,
                po_quantity=ordered,
                invoice_quantity=invoiced,
                received_quantity=received,
                po_unit_price=po_price,
                invoice_unit_price=invoice_price,
                status="exception" if notes else "matched",
                notes=notes,
            )
        )
    rules.append(received_fail or _rule("received_quantity", "PASS", "LOW", "Received quantity covers the order."))
    rules.append(quantity_fail or _rule("quantity", "PASS", "LOW", "Invoice quantity matches the quantity received."))
    rules.append(price_fail or _rule("unit_price", "PASS", "LOW", "Unit price matches the purchase order."))
    return rules


def _display(documents: list[Document]) -> tuple[str | None, str | None, Decimal | None, Decimal | None, Decimal | None]:
    purchase_orders = [doc for doc in documents if doc.document_type == "purchase_order"]
    invoices = [doc for doc in documents if doc.document_type == "invoice"]
    receipts = [doc for doc in documents if doc.document_type == "goods_receipt"]
    vendor_source = purchase_orders or invoices or receipts
    vendor_name = vendor_source[0].vendor.name if vendor_source else None
    currency = documents[0].currency if documents else None
    return vendor_name, currency, _combined_total(purchase_orders), _combined_total(invoices), _combined_total(receipts)


def _checks(documents: list[Document], codes: list[ExceptionCode]) -> list[MatchCheck]:
    types = {document.document_type for document in documents}
    has_po = "purchase_order" in types
    has_invoice = "invoice" in types
    has_receipt = "goods_receipt" in types
    blocked = set(codes)
    return [
        MatchCheck(label="Purchase order found", passed=has_po),
        MatchCheck(label="Invoice found", passed=has_invoice),
        MatchCheck(label="Goods receipt found", passed=has_receipt),
        MatchCheck(label="Vendor matched", passed=has_po and "vendor_mismatch" not in blocked),
        MatchCheck(label="Invoice number unique", passed=has_invoice and "duplicate_invoice" not in blocked),
        MatchCheck(label="Currency agrees", passed=_same_currency(documents)),
        MatchCheck(
            label="Quantity within receipt",
            passed=has_po
            and has_invoice
            and has_receipt
            and "quantity_mismatch" not in blocked
            and "partial_delivery" not in blocked,
        ),
        MatchCheck(label="Unit price matches PO", passed=has_po and has_invoice and "price_mismatch" not in blocked),
        MatchCheck(label="Totals agree", passed=has_po and has_invoice and "total_mismatch" not in blocked),
    ]


def _header_from(documents: list[Document]) -> tuple[str | None, str | None, str | None]:
    purchase_orders = [doc for doc in documents if doc.document_type == "purchase_order"]
    invoices = [doc for doc in documents if doc.document_type == "invoice"]
    receipts = [doc for doc in documents if doc.document_type == "goods_receipt"]
    po_number = purchase_orders[0].document_number if purchase_orders else (invoices[0].po_number if invoices else None)
    invoice_number = invoices[0].document_number if invoices else None
    grn_number = receipts[0].document_number if receipts else None
    return po_number, invoice_number, grn_number


def _summary(
    codes: list[ExceptionCode],
    header: tuple[str | None, str | None, str | None],
    lines: list[LineComparison],
) -> str:
    po_number, invoice_number, grn_number = header
    if "extraction_failed" in codes and len(codes) == 1:
        return "No structured purchase order, invoice, or goods receipt was extracted."
    if not codes:
        return f"PO {po_number}, invoice {invoice_number}, and goods receipt {grn_number} match."
    if codes == ["missing_document"]:
        return f"A three-way match needs a purchase order, an invoice, and a goods receipt for {po_number or 'the same PO'}."
    labels = ", ".join(code.replace("_", " ") for code in codes)
    detail = next((note for line in lines for note in line.notes), None)
    summary = f"Exceptions: {labels}."
    if detail:
        summary = f"{summary} {detail}"
    return summary


def _status(codes: list[ExceptionCode]) -> str:
    if not codes:
        return "matched"
    if set(codes) <= {"extraction_failed", "missing_document"}:
        return "incomplete"
    return "exception"


def _ordered(codes: list[ExceptionCode]) -> list[ExceptionCode]:
    rank = {code: index for index, code in enumerate(SEVERITY)}
    unique = list(dict.fromkeys(codes))
    return sorted(unique, key=lambda code: rank.get(code, len(rank)))


def _same_currency(documents: list[Document]) -> bool:
    if not documents:
        return False
    currencies = {document.currency.upper() for document in documents if document.currency}
    return len(currencies) <= 1


def _one_per_invoice_number(documents: list[Document]) -> list[Document]:
    """Keep the first copy of each invoice number for price, quantity, and total checks."""
    seen: set[str] = set()
    kept: list[Document] = []
    for document in documents:
        if document.document_type != "invoice":
            kept.append(document)
            continue
        key = document.document_number.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(document)
    return kept


def _group_key(document: Document) -> str:
    raw = document.document_number if document.document_type == "purchase_order" else document.po_number
    return "".join(raw.split()).casefold()


def _combined_total(documents: list[Document]) -> Decimal | None:
    totals = [document.total for document in documents if document.total is not None]
    if len(totals) != len(documents) or not totals:
        return None
    return sum(totals, Decimal("0"))


def _combined_tax(documents: list[Document]) -> Decimal | None:
    if not documents:
        return None
    taxes = [document.tax for document in documents]
    if any(tax is None for tax in taxes):
        return None
    return sum((tax for tax in taxes if tax is not None), Decimal("0"))


def _same_money(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return _totals_close(left, right)


def _show(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal('0.01'))}"


def _vendor_label(vendor: Party) -> str:
    if vendor.tax_id:
        return f"{vendor.name} ({vendor.tax_id})"
    return vendor.name


def _totals_close(left: Decimal, right: Decimal) -> bool:
    from app.pipeline.validate import money_close

    return money_close(left, right)


def _index_lines(documents: list[Document]) -> dict[str, list[LineItem]]:
    indexed: dict[str, list[LineItem]] = {}
    for document in documents:
        for line in document.line_items:
            indexed.setdefault(_line_key(line), []).append(line)
    return indexed


def _line_key(line: LineItem) -> str:
    if line.sku:
        return f"sku:{''.join(line.sku.split()).casefold()}"
    return "desc:" + "".join(char for char in line.description.casefold() if char.isalnum())


def _quantity(lines: list[LineItem]) -> Decimal | None:
    if not lines:
        return None
    return sum((line.quantity for line in lines), Decimal("0"))


def _unit_price(lines: list[LineItem]) -> Decimal | None:
    for line in lines:
        if line.unit_price is not None:
            return line.unit_price
    return None


def _format_qty(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"
