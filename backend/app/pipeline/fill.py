"""Ask the local model to fill a page the layout parser could not finish.

The whole page goes in one prompt. There is no chunking and no embedding.
A finished extraction is cached in Redis so the same page is not read twice.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.pipeline.ollama import Completion, OllamaError, ollama_complete
from app.pipeline.parse import _confidence
from app.pipeline.scores import stamp
from app.pipeline.read_text import ReadText
from app.schemas.documents import Extraction, GoodsReceipt, Invoice, LineItem, Party, PurchaseOrder
from app.services.cache import MemoryCache, get_cache

PROMPT_VERSION = "2"
SCHEMA = """{
  "document_type": null,
  "document_number": null,
  "document_date": null,
  "currency": null,
  "po_number": null,
  "received_by": null,
  "vendor": {"name": null, "tax_id": null, "address": null},
  "line_items": [
    {"sku": null, "description": null, "quantity": null, "unit": null, "unit_price": null, "amount": null}
  ],
  "subtotal": null,
  "tax": null,
  "total": null
}"""

Completer = Callable[[str], Completion]
Cache = MemoryCache | Any


def fill_from_page(
    file_id: str,
    source_name: str | None,
    read: ReadText,
    *,
    cache: Cache | None = None,
    completer: Completer | None = None,
) -> Extraction:
    settings = get_settings()
    store = cache if cache is not None else get_cache()
    text_hash = hashlib.sha256(read.text.encode("utf-8")).hexdigest()
    cache_key = _extract_key(settings.ollama_model, read, text_hash)
    cached = _cached_extraction(store, cache_key, file_id, source_name)
    if cached is not None:
        return cached

    warnings: list[str] = []
    if not store.available:
        warnings.append("Redis is unavailable, so this extraction was not cached.")

    complete = completer or ollama_complete
    try:
        completion = complete(_prompt(read.text))
    except OllamaError as exc:
        warnings.append(str(exc))
        return _empty(file_id, source_name, read, settings.ollama_model, warnings)

    try:
        payload = _json_object(completion.content)
    except ValueError as exc:
        warnings.append(f"The model did not return readable JSON ({exc}).")
        return _empty(
            file_id,
            source_name,
            read,
            settings.ollama_model,
            warnings,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )

    parsed = _from_payload(payload, read.text)
    warnings.extend(parsed.warnings)
    confidence = _confidence(
        document_type=parsed.document_type,
        number=parsed.number,
        vendor=parsed.vendor,
        line_items=parsed.line_items,
        total=parsed.total,
        issued=parsed.issued,
        currency=parsed.currency,
        po_number=parsed.po_number,
        source=read.source,
        ocr_confidence=read.ocr_confidence,
    )
    extraction = Extraction(
        file_id=file_id,
        source_name=source_name,
        document_type=parsed.document.document_type if parsed.document is not None else parsed.document_type,
        confidence=confidence,
        document=parsed.document,
        warnings=warnings,
        extractor=f"ollama:{settings.ollama_model}",
        ocr_confidence=read.ocr_confidence,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    extraction = stamp(
        extraction,
        source=read.source,
        ocr_confidence=read.ocr_confidence,
        model=parsed.document is not None,
    )
    if parsed.document is not None and store.available:
        store.set_json(cache_key, extraction.model_dump(mode="json"), settings.cache_ttl_seconds)
    return extraction


@dataclass
class _Parsed:
    document_type: str | None
    number: str | None
    vendor: str | None
    line_items: list[LineItem]
    total: Decimal | None
    issued: object
    currency: str | None
    po_number: str | None
    document: PurchaseOrder | Invoice | GoodsReceipt | None
    warnings: list[str]


def _from_payload(payload: dict, text: str) -> _Parsed:
    document_type = _document_type(payload.get("document_type"))
    number = _text(payload.get("document_number"))
    vendor_raw = payload.get("vendor") if isinstance(payload.get("vendor"), dict) else {}
    vendor_name = _text(vendor_raw.get("name"))
    po_number = _text(payload.get("po_number"))
    issued = _date(payload.get("document_date"))
    currency = _currency(payload.get("currency"))
    if currency is None and re.search(r"Rs\.?|INR|₹", text, re.IGNORECASE):
        currency = "INR"
    line_items = _lines(payload.get("line_items"))
    total = _decimal(payload.get("total"))
    warnings: list[str] = []
    document = None
    if document_type is None or number is None or vendor_name is None:
        warnings.append("The model did not find a document type, vendor, or document number.")
    elif document_type != "purchase_order" and not po_number:
        warnings.append("Invoice and goods receipt need a PO number.")
    else:
        fields = {
            "document_number": number,
            "document_date": issued,
            "currency": currency or "INR",
            "vendor": Party(
                name=vendor_name,
                tax_id=_text(vendor_raw.get("tax_id")),
                address=_text(vendor_raw.get("address")),
            ),
            "line_items": line_items,
            "subtotal": _decimal(payload.get("subtotal")),
            "tax": _decimal(payload.get("tax")),
            "total": total,
        }
        try:
            if document_type == "purchase_order":
                document = PurchaseOrder(**fields)
            elif document_type == "invoice":
                document = Invoice(**fields, po_number=po_number or "")
            else:
                document = GoodsReceipt(**fields, po_number=po_number or "", received_by=_text(payload.get("received_by")))
        except ValidationError as exc:
            warnings.append(exc.errors()[0]["msg"] if exc.errors() else "Schema validation failed.")
    return _Parsed(
        document_type=document_type,
        number=number,
        vendor=vendor_name,
        line_items=line_items,
        total=total,
        issued=issued,
        currency=currency,
        po_number=po_number,
        document=document,
        warnings=warnings,
    )


def _cached_extraction(store: Cache, key: str, file_id: str, source_name: str | None) -> Extraction | None:
    cached = store.get_json(key) if store.available else None
    if not isinstance(cached, dict):
        return None
    payload = dict(cached)
    payload["file_id"] = file_id
    payload["source_name"] = source_name
    try:
        return Extraction.model_validate(payload)
    except ValidationError:
        return None


def _prompt(text: str) -> str:
    return (
        "Fill this JSON object from the page. Use null when the page does not state the value.\n\n"
        f"{SCHEMA}\n\nPage:\n{text}"
    )


def _extract_key(model: str, read: ReadText, text_hash: str) -> str:
    ocr = "none" if read.ocr_confidence is None else f"{read.ocr_confidence:.4f}"
    return f"ap:extract:{PROMPT_VERSION}:{model}:{read.source}:{ocr}:{text_hash}"


def _json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence != -1:
            text = text[:fence]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON was not an object")
    return data


def _empty(
    file_id: str,
    source_name: str | None,
    read: ReadText,
    model: str,
    warnings: list[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Extraction:
    return stamp(
        Extraction(
            file_id=file_id,
            source_name=source_name,
            confidence=0,
            completeness=0,
            warnings=warnings,
            extractor=f"ollama:{model}",
            ocr_confidence=read.ocr_confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        source=read.source,
        ocr_confidence=read.ocr_confidence,
    )


def _document_type(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    folded = " ".join(text.casefold().replace("-", " ").replace("_", " ").split())
    return {
        "purchase order": "purchase_order",
        "po": "purchase_order",
        "invoice": "invoice",
        "tax invoice": "invoice",
        "goods receipt": "goods_receipt",
        "goods receipt note": "goods_receipt",
        "grn": "goods_receipt",
    }.get(folded)


def _lines(value: object) -> list[LineItem]:
    if not isinstance(value, list):
        return []
    items: list[LineItem] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        description = _text(entry.get("description"))
        if description is None:
            continue
        quantity = _decimal(entry.get("quantity")) or Decimal("0")
        items.append(
            LineItem(
                description=description,
                quantity=quantity,
                unit=_text(entry.get("unit")),
                unit_price=_decimal(entry.get("unit_price")),
                amount=_decimal(entry.get("amount")),
                sku=_text(entry.get("sku")),
            )
        )
    return items


def _date(value: object):
    text = _text(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _currency(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if "₹" in text or re.search(r"\bRs\.?\b", text, re.IGNORECASE):
        return "INR"
    letters = "".join(char for char in text if char.isalpha()).upper()
    if len(letters) >= 3:
        return letters[:3]
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"(?i)\b(rs\.?|inr)\b", "", text.replace(",", "").replace("₹", "")).strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
