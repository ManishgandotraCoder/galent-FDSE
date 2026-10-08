"""Build a document from OCR word boxes.

A skewed photograph does not come back as one line per table row. Each cell
is its own box. Columns are taken from the header words, and a row is the
cells that belong to the same SKU from top to bottom. The printed total is
kept as printed.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.pipeline.read_text import OcrToken
from app.schemas.documents import GoodsReceipt, Invoice, LineItem, Party, PurchaseOrder

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")
DATE_RE = re.compile(r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}")

HEADER_KEYS = ("sku", "description", "qty", "unit", "rate", "amount")
STOP_LABELS = {
    "document no",
    "date",
    "po number",
    "bill to",
    "ship to",
    "received at",
    "received by",
    "gate entry",
    "vehicle",
    "remarks",
    "sku",
    "description",
    "qty",
    "unit",
    "rate",
    "amount",
    "subtotal",
    "total",
}


def parse_ocr_tokens(
    tokens: list[OcrToken],
) -> tuple[PurchaseOrder | Invoice | GoodsReceipt | None, list[str]]:
    warnings: list[str] = []
    document_type = _document_type(tokens)
    if document_type is None:
        warnings.append("Could not tell whether this is a purchase order, invoice, or goods receipt.")
        return None, warnings

    number = _code(_value_below(tokens, "document no"))
    issued = _parse_date(_text_below(tokens, "date"))
    po_number = _code(_value_below(tokens, "po number"))
    received_by = _text_below(tokens, "received by")
    vendor_name, vendor_address, vendor_tax = _vendor(tokens)
    if vendor_name is None and vendor_tax:
        vendor_name = vendor_tax
        warnings.append("The vendor name was not readable. The GSTIN is being used in its place.")
    line_items = _line_items(tokens)
    amounts = _total_amounts(tokens)
    subtotal = amounts.get("subtotal")
    cgst = amounts.get("cgst")
    sgst = amounts.get("sgst")
    total = amounts.get("total")
    value_received = amounts.get("value received")
    if value_received is not None and total is None:
        total = value_received
        if subtotal is None:
            subtotal = value_received
        if cgst is None and sgst is None:
            cgst = Decimal("0")
            sgst = Decimal("0")
    tax = None
    if cgst is not None or sgst is not None:
        tax = (cgst or Decimal("0")) + (sgst or Decimal("0"))
    if subtotal is None and line_items and all(item.amount is not None for item in line_items):
        subtotal = sum((item.amount or Decimal("0") for item in line_items), Decimal("0"))
    currency = "INR" if any(re.search(r"Rs\.?|INR|₹", token.text, re.IGNORECASE) for token in tokens) else None

    if vendor_name is None or number is None:
        warnings.append("Vendor or document number was not found.")
        return None, warnings
    if document_type != "purchase_order" and not po_number:
        warnings.append("Invoice and goods receipt need a PO number.")
        return None, warnings

    payload = {
        "document_number": number,
        "document_date": issued,
        "currency": currency or "INR",
        "vendor": Party(name=vendor_name, tax_id=vendor_tax, address=vendor_address),
        "line_items": line_items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
    }
    if document_type == "purchase_order":
        return PurchaseOrder(**payload), warnings
    if document_type == "invoice":
        return Invoice(**payload, po_number=po_number or ""), warnings
    return GoodsReceipt(**payload, po_number=po_number or "", received_by=received_by), warnings


def _document_type(tokens: list[OcrToken]) -> str | None:
    top = " ".join(token.text for token in sorted(tokens, key=lambda item: -item.mid_y)[:8]).casefold()
    if "goods receipt" in top:
        return "goods_receipt"
    if "purchase order" in top:
        return "purchase_order"
    if "tax invoice" in top or "invoice" in top or any("कर चालान" in token.text for token in tokens):
        return "invoice"
    return None


def _vendor(tokens: list[OcrToken]) -> tuple[str | None, str | None, str | None]:
    anchor = _find_label(tokens, "supplier")
    if anchor is None:
        return None, None, None
    left = anchor.xmin - 0.02
    right = anchor.xmin + 0.36
    chosen = [
        token
        for token in tokens
        if left <= token.center_x <= right and token.mid_y < anchor.mid_y - 0.004
    ]
    chosen.sort(key=lambda token: -token.mid_y)
    block: list[OcrToken] = []
    previous_y = anchor.mid_y
    for token in chosen:
        if previous_y - token.mid_y > 0.06 and block:
            break
        folded = token.text.strip().casefold()
        if folded in STOP_LABELS or folded.startswith("gstin"):
            if folded.startswith("gstin"):
                block.append(token)
            break
        block.append(token)
        previous_y = token.mid_y
    tax_id = None
    body: list[str] = []
    for token in block:
        found = _gstin(token.text)
        if found:
            tax_id = found
            break
        body.append(token.text.strip())
    if not body:
        return None, None, tax_id
    name = body[0]
    address = " ".join(body[1:]).strip() or None
    return name, address, tax_id


def _line_items(tokens: list[OcrToken]) -> list[LineItem]:
    headers: dict[str, OcrToken] = {}
    for token in tokens:
        key = token.text.strip().casefold()
        if key in HEADER_KEYS and key not in headers:
            headers[key] = token
    if "sku" not in headers:
        return []
    ordered = [key for key in HEADER_KEYS if key in headers]
    centers = {key: headers[key].center_x for key in ordered}
    ranges: list[tuple[str, float, float]] = []
    for index, key in enumerate(ordered):
        # Stay to the right of the row-number column. Those digits sit just left of the SKU.
        left = headers[key].xmin - 0.012 if index == 0 else (centers[ordered[index - 1]] + centers[key]) / 2
        right = 1.0 if index == len(ordered) - 1 else (centers[key] + centers[ordered[index + 1]]) / 2
        ranges.append((key, left, right))

    ceiling = _totals_ceiling(tokens)
    columns: dict[str, list[OcrToken]] = {key: [] for key in ordered}
    for token in tokens:
        if ceiling is not None and token.mid_y <= ceiling:
            continue
        for key, left, right in ranges:
            if not (left <= token.center_x < right):
                continue
            # A rotated page lifts the right side, so compare with this column's header only.
            if token is headers[key] or token.mid_y >= headers[key].ymin:
                break
            columns[key].append(token)
            break

    anchors = sorted(columns["sku"], key=lambda token: -token.mid_y)
    if not anchors:
        return []
    aligned: dict[str, list[OcrToken | None]] = {"sku": anchors}
    for key in ordered:
        if key == "sku":
            continue
        aligned[key] = _zip_column(columns[key], anchors)

    items: list[LineItem] = []
    for index, anchor in enumerate(anchors):
        cells = {key: aligned[key][index].text if aligned[key][index] is not None else None for key in ordered}
        item = _line_from_cells(anchor.text if cells.get("sku") is None else cells["sku"], cells)
        if item is not None:
            items.append(item)
    return items


def _zip_column(column: list[OcrToken], anchors: list[OcrToken]) -> list[OcrToken | None]:
    pool = [
        token
        for token in column
        if min(abs(token.mid_y - anchor.mid_y) for anchor in anchors) <= 0.06
    ]
    pool.sort(key=lambda token: -token.mid_y)
    paired: list[OcrToken | None] = []
    cursor = 0
    for anchor in anchors:
        if cursor >= len(pool):
            paired.append(None)
            continue
        if abs(pool[cursor].mid_y - anchor.mid_y) <= 0.06:
            paired.append(pool[cursor])
            cursor += 1
        else:
            paired.append(None)
    return paired


def _line_from_cells(sku_text: str, cells: dict[str, str | None]) -> LineItem | None:
    sku = _sku(sku_text)
    description = (cells.get("description") or "").strip() or sku
    quantity = _plain_decimal(cells.get("qty"))
    if not sku or not description or quantity is None:
        return None
    return LineItem(
        sku=sku,
        description=description,
        quantity=quantity,
        unit=(cells.get("unit") or "").strip() or None,
        unit_price=_money(cells.get("rate")),
        amount=_money(cells.get("amount")),
    )


def _sku(text: str) -> str:
    match = re.fullmatch(r"\d+\s+([A-Za-z][A-Za-z0-9-]*)", text.strip())
    if match:
        return match.group(1)
    return text.strip()


def _totals_ceiling(tokens: list[OcrToken]) -> float | None:
    marks = []
    for name in ("subtotal", "cgst", "sgst", "total", "value received"):
        label = _find_label(tokens, name)
        if label is not None:
            marks.append(label.mid_y)
    if not marks:
        return None
    return max(marks)


def _total_amounts(tokens: list[OcrToken]) -> dict[str, Decimal]:
    """Pair total labels with the amounts in the same vertical order.

    On a skewed page the amount sits higher than its label, so the nearest
    amount in Y can belong to the row below.
    """

    names = ("subtotal", "cgst", "sgst", "total", "value received")
    labels = [(name, label) for name in names if (label := _find_label(tokens, name)) is not None]
    if not labels:
        return {}
    labels.sort(key=lambda item: -item[1].mid_y)
    top = labels[0][1].mid_y + 0.025
    bottom = labels[-1][1].mid_y - 0.025
    left = max(label.xmax for _, label in labels)
    moneys: list[tuple[OcrToken, Decimal]] = []
    for token in tokens:
        if token.center_x <= left + 0.02:
            continue
        if not (bottom <= token.mid_y <= top):
            continue
        amount = _money(token.text)
        if amount is None:
            continue
        moneys.append((token, amount))
    moneys.sort(key=lambda item: -item[0].mid_y)
    if len(moneys) != len(labels):
        found: dict[str, Decimal] = {}
        for name, _label in labels:
            amount = _money_beside(tokens, name)
            if amount is not None:
                found[name] = amount
        return found
    return {name: amount for (name, _label), (_token, amount) in zip(labels, moneys, strict=True)}


def _money_beside(tokens: list[OcrToken], label: str) -> Decimal | None:
    anchor = _find_label(tokens, label)
    if anchor is None:
        return None
    best: tuple[float, Decimal] | None = None
    for token in tokens:
        if token.center_x <= anchor.xmax:
            continue
        gap = abs(token.mid_y - anchor.mid_y)
        if gap > 0.02:
            continue
        amount = _money(token.text)
        if amount is None:
            continue
        if best is None or gap < best[0]:
            best = (gap, amount)
    return best[1] if best else None


def _value_below(tokens: list[OcrToken], label: str) -> OcrToken | None:
    anchor = _find_label(tokens, label)
    if anchor is None:
        return None
    best: OcrToken | None = None
    for token in tokens:
        if token is anchor:
            continue
        if token.mid_y >= anchor.mid_y:
            continue
        if not (anchor.xmin - 0.03 <= token.center_x <= anchor.xmax + 0.05):
            continue
        if anchor.mid_y - token.mid_y > 0.045:
            continue
        if best is None or token.mid_y > best.mid_y:
            best = token
    return best


def _text_below(tokens: list[OcrToken], label: str) -> str | None:
    token = _value_below(tokens, label)
    return token.text.strip() if token else None


def _find_label(tokens: list[OcrToken], name: str) -> OcrToken | None:
    folded = name.casefold()
    for token in tokens:
        text = token.text.strip().casefold()
        if folded == "total" and text.startswith("subtotal"):
            continue
        if text == folded or text.startswith(folded + " ") or text.startswith(folded + ":"):
            return token
    return None


def _code(token: OcrToken | None) -> str | None:
    if token is None:
        return None
    match = re.fullmatch(r"(?i)((?:PO|INV|GRN)-\d+)", token.text.strip())
    if match is None:
        return None
    return match.group(1).upper()


def _gstin(text: str) -> str | None:
    match = GSTIN_RE.search(text.upper())
    if match:
        return match.group(0)
    compact = re.sub(r"\s+", "", text.upper())
    match = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]", compact)
    return match.group(0) if match else None


def _money(text: str | None) -> Decimal | None:
    if not text:
        return None
    cleaned = re.sub(r"(?i)(?:rs\.?|inr|₹)", "", text).replace(" ", "")
    grouped = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)[.,](\d{2})", cleaned)
    if grouped:
        whole = re.sub(r"[.,]", "", grouped.group(1))
        return _decimal(f"{whole}.{grouped.group(2)}")
    simple = re.fullmatch(r"(\d+)[.,](\d{2})", cleaned)
    if simple:
        return _decimal(f"{simple.group(1)}.{simple.group(2)}")
    if re.fullmatch(r"\d+", cleaned):
        return _decimal(cleaned)
    return None


def _plain_decimal(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if match is None:
        return None
    return _decimal(match.group(0))


def _parse_date(value: str | None):
    if not value:
        return None
    match = DATE_RE.search(value)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(0), "%d %b %Y").date()
    except ValueError:
        return None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
