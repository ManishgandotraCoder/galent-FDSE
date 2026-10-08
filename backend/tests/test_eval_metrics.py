from app.eval.metrics import exception_counts, field_counts, percentile, ratio, routing_rates


def test_field_accuracy_ignores_formatting_and_counts_misses():
    expected = {
        "document_number": "INV-1",
        "total": "1000.00",
        "vendor": {"name": "Acme"},
        "line_items": [{"sku": "A", "quantity": "10", "description": "Bolt"}],
    }
    predicted = {
        "document_number": "INV-1",
        "total": "1000",
        "vendor": {"name": "acme"},
        "line_items": [{"sku": "A", "quantity": "10", "description": "Nut"}],
    }
    correct, total = field_counts(expected, predicted)
    assert (correct, total) == (5, 6)
    assert ratio(correct, total) == 5 / 6


def test_exception_precision_and_recall_are_micro_averaged():
    true_positive, false_positive, false_negative = exception_counts(
        [
            (["quantity_mismatch", "partial_delivery"], ["quantity_mismatch", "partial_delivery"]),
            (["total_mismatch"], ["vendor_mismatch"]),
            ([], []),
        ]
    )
    assert (true_positive, false_positive, false_negative) == (2, 1, 1)
    assert ratio(true_positive, true_positive + false_positive) == 2 / 3
    assert ratio(true_positive, true_positive + false_negative) == 2 / 3


def test_false_auto_clear_is_the_share_of_bad_clears():
    rates = routing_rates(
        [
            ("auto_clear", "auto_clear"),
            ("flag", "auto_clear"),
            ("reject", "reject"),
            ("flag", "flag"),
        ]
    )
    assert rates["false_auto_clear_rate"] == 0.5
    assert rates["auto_clear_precision"] == 0.5
    assert rates["auto_clear_recall"] == 1
    assert rates["false_rejection_rate"] == 0
    assert rates["human_review_rate"] == 0.25


def test_percentile_uses_the_nearest_rank():
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.95) == 0
