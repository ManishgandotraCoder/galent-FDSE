"""Layout parser for the Northwind sample packet.

The live pipeline tries this reader first. The local model runs only when a
required field is still missing. Totals are taken from the printed figures,
not recomputed.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.pipeline.parse_layout import parse_ocr_tokens
from app.pipeline.read_text import ReadText
from app.pipeline.scores import stamp
from app.schemas.documents import Extraction, GoodsReceipt, Invoice, LineItem, Party, PurchaseOrder

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")
MONEY_RE = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+\.\d{2})", re.IGNORECASE)
LINE_RE = re.compile(
    r"^(?P<idx>\d+)\s+(?P<sku>[A-Za-z][A-Za-z0-9-]*)\s+"
    r"(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit>[A-Za-z]+)\s+"
    r"(?:Rs\.?|INR|₹)\s*(?P<rate>[\d,]+\.\d{2})\s+"
    r"(?:Rs\.?|INR|₹)\s*(?P<amount>[\d,]+\.\d{2})\s*$",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}")
PARTY_STOPS = (
    "BILL TO",
    "SUPPLIER",
    "SHIP TO",
    "RECEIVED AT",
    "DOCUMENT NO",
    "DATE",
    "PO NUMBER",
    "RECEIVED BY",
    "GATE ENTRY",
    "VEHICLE",
    "REMARKS",
)


def parse_read(file_id: str, source_name: str | None, read: ReadText) -> Extraction:
    if not read.text.strip() and not read.tokens:
        warning = read.warnings[0] if read.warnings else "No text could be read from this file."
        return stamp(
            Extraction(
                file_id=file_id,
                source_name=source_name,
                confidence=0,
                warnings=[warning, *read.warnings[1:]],
                extractor=read.source,
            ),
            source=read.source,
            ocr_confidence=read.ocr_confidence,
        )

    if len(read.pages) > 1 and not read.tokens:
        parsed, confidence, warnings = _parse_pages(read)
        warnings = [*read.warnings, *warnings]
        return stamp(
            Extraction(
                file_id=file_id,
                source_name=source_name,
                document_type=parsed.document_type if parsed is not None else _detect_type(read.text),
                confidence=confidence,
                document=parsed,
                warnings=warnings,
                extractor=read.source,
                ocr_confidence=read.ocr_confidence,
            ),
            source=read.source,
            ocr_confidence=read.ocr_confidence,
        )

    if read.tokens:
        parsed, layout_warnings = parse_ocr_tokens(read.tokens)
        warnings = [*read.warnings, *layout_warnings]
        if _missing_lines_or_total(parsed):
            text_doc, _, text_warnings = _parse_text(read)
            if text_doc is not None and not _missing_lines_or_total(text_doc):
                parsed = text_doc
                warnings = [*warnings, *text_warnings]
        confidence = _confidence(
            document_type=parsed.document_type if parsed is not None else None,
            number=parsed.document_number if parsed is not None else None,
            vendor=parsed.vendor.name if parsed is not None else None,
            line_items=list(parsed.line_items) if parsed is not None else [],
            total=parsed.total if parsed is not None else None,
            issued=parsed.document_date if parsed is not None else None,
            currency=parsed.currency if parsed is not None else None,
            po_number=getattr(parsed, "po_number", None) if parsed is not None else None,
            source=read.source,
            ocr_confidence=read.ocr_confidence,
        )
        return stamp(
            Extraction(
                file_id=file_id,
                source_name=source_name,
                document_type=parsed.document_type if parsed is not None else None,
                confidence=confidence,
                document=parsed,
                warnings=warnings,
                extractor=read.source,
                ocr_confidence=read.ocr_confidence,
            ),
            source=read.source,
            ocr_confidence=read.ocr_confidence,
        )

    parsed, confidence, warnings = _parse_text(read)
    warnings = [*read.warnings, *warnings]
    return stamp(
        Extraction(
            file_id=file_id,
            source_name=source_name,
            document_type=parsed.document_type if parsed is not None else _detect_type(read.text),
            confidence=confidence,
            document=parsed,
            warnings=warnings,
            extractor=read.source,
            ocr_confidence=read.ocr_confidence,
        ),
        source=read.source,
        ocr_confidence=read.ocr_confidence,
    )


def _parse_pages(read: ReadText) -> tuple[PurchaseOrder | Invoice | GoodsReceipt | None, float, list[str]]:
    """Header from the first page that has it, line items from every page, totals from the last page that prints them."""
    return _document_from_fields(_merge_fields([_collect_fields(page) for page in read.pages]), read)


def _missing_lines_or_total(document: PurchaseOrder | Invoice | GoodsReceipt | None) -> bool:
    return document is None or not document.line_items or document.total is None


def _parse_text(read: ReadText) -> tuple[PurchaseOrder | Invoice | GoodsReceipt | None, float, list[str]]:
    return _document_from_fields(_collect_fields(read.text), read)


def _collect_fields(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    document_type = _detect_type(joined)
    number = _labeled(lines, "DOCUMENT NO") or _first(r"\b((?:PO|INV|GRN)-\d+)\b", joined)
    vendor_name, vendor_address, vendor_tax = _vendor(lines, document_type or "purchase_order")
    line_items = _line_items(lines)
    subtotal = _amount_for(lines, "SUBTOTAL")
    cgst = _amount_for(lines, "CGST")
    sgst = _amount_for(lines, "SGST")
    total = _amount_for(lines, "TOTAL")
    value_received = _amount_for(lines, "VALUE RECEIVED")
    if value_received is not None and total is None:
        total = value_received
        subtotal = subtotal if subtotal is not None else value_received
        if cgst is None and sgst is None:
            cgst = Decimal("0")
            sgst = Decimal("0")
    tax = (cgst or Decimal("0")) + (sgst or Decimal("0")) if cgst is not None or sgst is not None else None
    if subtotal is None and line_items and all(item.amount is not None for item in line_items):
        subtotal = sum((item.amount or Decimal("0") for item in line_items), Decimal("0"))
    return {
        "document_type": document_type,
        "number": number,
        "issued": _date(_labeled(lines, "DATE")),
        "po_number": _labeled(lines, "PO NUMBER"),
        "received_by": _labeled(lines, "RECEIVED BY"),
        "vendor_name": vendor_name,
        "vendor_address": vendor_address,
        "vendor_tax": vendor_tax,
        "line_items": line_items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "currency": "INR" if re.search(r"Rs\.?|INR|₹", joined, re.IGNORECASE) else None,
    }


def _merge_fields(rows: list[dict]) -> dict:
    merged = {
        "document_type": _first_present(rows, "document_type"),
        "number": _first_present(rows, "number"),
        "issued": _first_present(rows, "issued"),
        "po_number": _first_present(rows, "po_number"),
        "received_by": _first_present(rows, "received_by"),
        "vendor_name": _first_present(rows, "vendor_name"),
        "vendor_address": _first_present(rows, "vendor_address"),
        "vendor_tax": _first_present(rows, "vendor_tax"),
        "line_items": [item for row in rows for item in row["line_items"]],
        "subtotal": _last_present(rows, "subtotal"),
        "tax": _last_present(rows, "tax"),
        "total": _last_present(rows, "total"),
        "currency": _first_present(rows, "currency"),
    }
    return merged


def _first_present(rows: list[dict], key: str):
    for row in rows:
        if row[key] not in (None, ""):
            return row[key]
    return None


def _last_present(rows: list[dict], key: str):
    for row in reversed(rows):
        if row[key] is not None:
            return row[key]
    return None


def merge_documents(
    documents: list[PurchaseOrder | Invoice | GoodsReceipt],
) -> tuple[PurchaseOrder | Invoice | GoodsReceipt | None, float]:
    """Same merge as a multi-page read: header from the first document, lines from all, totals from the last."""
    if not documents:
        return None, 0.0
    rows = []
    for document in documents:
        rows.append(
            {
                "document_type": document.document_type,
                "number": document.document_number,
                "issued": document.document_date,
                "po_number": getattr(document, "po_number", None),
                "received_by": getattr(document, "received_by", None),
                "vendor_name": document.vendor.name,
                "vendor_address": document.vendor.address,
                "vendor_tax": document.vendor.tax_id,
                "line_items": list(document.line_items),
                "subtotal": document.subtotal,
                "tax": document.tax,
                "total": document.total,
                "currency": document.currency,
            }
        )
    merged = _merge_fields(rows)
    document, confidence, _warnings = _document_from_fields(merged, ReadText(text="merged", source="pdf"))
    return document, confidence


def _document_from_fields(fields: dict, read: ReadText) -> tuple[PurchaseOrder | Invoice | GoodsReceipt | None, float, list[str]]:
    document_type = fields["document_type"]
    number = fields["number"]
    vendor_name = fields["vendor_name"]
    line_items = fields["line_items"]
    total = fields["total"]
    issued = fields["issued"]
    currency = fields["currency"]
    po_number = fields["po_number"]
    warnings: list[str] = []
    if document_type is None:
        return None, 0.2 if read.source == "pdf" else 0.1, ["Could not tell whether this is a purchase order, invoice, or goods receipt."]

    confidence = _confidence(
        document_type=document_type,
        number=number,
        vendor=vendor_name,
        line_items=line_items,
        total=total,
        issued=issued,
        currency=currency,
        po_number=po_number,
        source=read.source,
        ocr_confidence=read.ocr_confidence,
    )

    if vendor_name is None or number is None:
        warnings.append("Vendor or document number was not found.")
        return None, confidence, warnings
    if document_type != "purchase_order" and not po_number:
        warnings.append("Invoice and goods receipt need a PO number.")
        return None, min(confidence, 0.6), warnings

    payload = {
        "document_number": number,
        "document_date": issued,
        "currency": currency or "INR",
        "vendor": Party(name=vendor_name, tax_id=fields["vendor_tax"], address=fields["vendor_address"]),
        "line_items": line_items,
        "subtotal": fields["subtotal"],
        "tax": fields["tax"],
        "total": total,
    }
    try:
        if document_type == "purchase_order":
            document = PurchaseOrder(**payload)
        elif document_type == "invoice":
            document = Invoice(**payload, po_number=po_number or "")
        else:
            document = GoodsReceipt(**payload, po_number=po_number or "", received_by=fields["received_by"])
    except ValidationError as exc:
        warnings.append(exc.errors()[0]["msg"] if exc.errors() else "Schema validation failed.")
        return None, min(confidence, 0.45), warnings
    return document, confidence, warnings


def _confidence(
    *,
    document_type: str | None,
    number: str | None,
    vendor: str | None,
    line_items: list[LineItem],
    total: Decimal | None,
    issued,
    currency: str | None,
    po_number: str | None,
    source: str,
    ocr_confidence: float | None,
) -> float:
    score = 0.0
    score += 0.16 if document_type else 0
    score += 0.16 if number else 0
    score += 0.14 if vendor else 0
    score += 0.18 if line_items else 0
    score += 0.14 if total is not None else 0
    score += 0.08 if issued else 0
    score += 0.06 if currency else 0
    needs_po = document_type in {"invoice", "goods_receipt"}
    score += 0.08 if po_number or not needs_po else 0
    if source == "ocr":
        # A photograph stays under the auto-clear line even when every field was found.
        measured = 0.90 if ocr_confidence is None else max(0.0, min(ocr_confidence, 1.0))
        score *= min(measured, 0.90)
    return round(min(score, 1.0), 4)


def _detect_type(text: str) -> str | None:
    folded = text.casefold()
    if "goods receipt note" in folded:
        return "goods_receipt"
    if "purchase order" in folded:
        return "purchase_order"
    if "tax invoice" in folded or "कर चालान" in text:
        return "invoice"
    number = _first(r"\b((?:PO|INV|GRN)-\d+)\b", text)
    if number is None:
        return None
    if number.startswith("PO-"):
        return "purchase_order"
    if number.startswith("GRN-"):
        return "goods_receipt"
    if number.startswith("INV-"):
        return "invoice"
    return None


def _vendor(lines: list[str], document_type: str) -> tuple[str | None, str | None, str | None]:
    block = _party_block(lines, "SUPPLIER")
    if not block and document_type == "invoice":
        block = _before_title(lines)
    if not block:
        return None, None, None
    tax_id = None
    tax_at = None
    for index, line in enumerate(block):
        match = GSTIN_RE.search(line.upper())
        if match:
            tax_id = match.group(0)
            tax_at = index
            break
    body = block if tax_at is None else block[:tax_at]
    body = [line for line in body if not line.upper().startswith("GSTIN") and line.upper() != "SUPPLIER"]
    if not body:
        return None, None, tax_id
    name = body[0]
    address = " ".join(body[1:]).strip() or None
    return name, address, tax_id


def _before_title(lines: list[str]) -> list[str]:
    collected: list[str] = []
    for line in lines:
        folded = line.casefold()
        if "tax invoice" in folded or "purchase order" in folded or "goods receipt note" in folded or "कर चालान" in line:
            break
        collected.append(line)
    return collected


def _party_block(lines: list[str], label: str) -> list[str]:
    capture = False
    block: list[str] = []
    for line in lines:
        upper = line.strip().upper()
        if upper == label or upper.startswith(label + " ") or upper.startswith(label + ":"):
            capture = True
            rest = line.strip()[len(label) :].strip(" :")
            block = [rest] if rest else []
            continue
        if not capture:
            continue
        if _is_stop(upper) or upper.startswith("#"):
            break
        block.append(line.strip())
    return [line for line in block if line]


def _is_stop(upper: str) -> bool:
    return any(upper == stop or upper.startswith(stop + " ") or upper.startswith(stop + ":") for stop in PARTY_STOPS)


def _line_items(lines: list[str]) -> list[LineItem]:
    items: list[LineItem] = []
    for line in lines:
        match = LINE_RE.match(line.strip())
        if match is None:
            continue
        items.append(
            LineItem(
                sku=match.group("sku"),
                description=match.group("desc").strip(),
                quantity=_decimal(match.group("qty")) or Decimal("0"),
                unit=match.group("unit"),
                unit_price=_decimal(match.group("rate")),
                amount=_decimal(match.group("amount")),
            )
        )
    return items


def _labeled(lines: list[str], label: str) -> str | None:
    prefix = label.upper()
    for index, line in enumerate(lines):
        upper = line.upper()
        if upper == prefix or upper.startswith(prefix + " ") or upper.startswith(prefix + ":"):
            rest = line[len(label) :].strip(" :")
            if rest:
                return rest.strip()
            if index + 1 < len(lines):
                return lines[index + 1].strip()
    return None


def _amount_for(lines: list[str], label: str) -> Decimal | None:
    prefix = label.upper()
    for line in lines:
        upper = line.upper()
        if prefix == "TOTAL":
            if re.search(r"(?<![A-Z])TOTAL\b", upper) is None:
                continue
        elif prefix not in upper:
            continue
        amounts = MONEY_RE.findall(line)
        if amounts:
            return _decimal(amounts[-1])
    return None


def _date(value: str | None):
    if not value:
        return None
    match = DATE_RE.search(value)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(0), "%d %b %Y").date()
    except ValueError:
        return None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None
