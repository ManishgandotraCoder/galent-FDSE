"""Score extracted fields and exception sets. No I/O."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation


def document_fields(document: dict | None) -> list[tuple[str, object]]:
    if not document:
        return []
    fields: list[tuple[str, object]] = []
    for key in (
        "document_type",
        "document_number",
        "document_date",
        "currency",
        "subtotal",
        "tax",
        "total",
        "po_number",
        "received_by",
    ):
        if document.get(key) is not None:
            fields.append((key, document[key]))
    vendor = document.get("vendor") or {}
    for key in ("name", "tax_id", "address"):
        if vendor.get(key) is not None:
            fields.append((f"vendor.{key}", vendor[key]))
    for index, line in enumerate(document.get("line_items") or []):
        for key in ("sku", "description", "quantity", "unit", "unit_price", "amount"):
            if line.get(key) is not None:
                fields.append((f"line_items[{index}].{key}", line[key]))
    return fields


def field_counts(expected: dict | None, predicted: dict | None) -> tuple[int, int]:
    expected_fields = document_fields(expected)
    predicted_map = dict(document_fields(predicted))
    correct = sum(1 for key, value in expected_fields if same(value, predicted_map.get(key)))
    return correct, len(expected_fields)


def same(expected: object, predicted: object) -> bool:
    if predicted is None:
        return expected is None
    left = _decimal(expected)
    right = _decimal(predicted)
    if left is not None and right is not None:
        return left == right
    return str(expected).strip().casefold() == str(predicted).strip().casefold()


def exception_counts(pairs: list[tuple[list[str], list[str]]]) -> tuple[int, int, int]:
    true_positive = false_positive = false_negative = 0
    for expected, predicted in pairs:
        expected_set = set(expected)
        predicted_set = set(predicted)
        true_positive += len(expected_set & predicted_set)
        false_positive += len(predicted_set - expected_set)
        false_negative += len(expected_set - predicted_set)
    return true_positive, false_positive, false_negative


def routing_rates(pairs: list[tuple[str, str]]) -> dict[str, float | int | None]:
    """Score the decision, not just the exception labels.

    False auto-clear is the share of automatic clears that should not have cleared.
    That is the failure that pays a bad invoice.
    """
    predicted_clear = [expected for expected, predicted in pairs if predicted == "auto_clear"]
    expected_clear = [predicted for expected, predicted in pairs if expected == "auto_clear"]
    true_clear = sum(1 for expected, predicted in pairs if expected == "auto_clear" and predicted == "auto_clear")
    false_clear = sum(1 for expected in predicted_clear if expected != "auto_clear")
    not_reject = [(expected, predicted) for expected, predicted in pairs if expected != "reject"]
    false_reject = sum(1 for _, predicted in not_reject if predicted == "reject")
    reviews = sum(1 for _, predicted in pairs if predicted == "flag")
    return {
        "cases": len(pairs),
        "false_auto_clear_rate": ratio(false_clear, len(predicted_clear)),
        "auto_clear_precision": ratio(true_clear, len(predicted_clear)),
        "auto_clear_recall": ratio(true_clear, len(expected_clear)),
        "false_rejection_rate": ratio(false_reject, len(not_reject)),
        "human_review_rate": ratio(reviews, len(pairs)) if pairs else None,
    }


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.replace(",", ""))
        except InvalidOperation:
            return None
    return None
