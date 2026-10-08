from app.eval.variants import build_cases, score_variants


def test_generated_cases_cover_the_router_and_do_not_clear_a_bad_invoice():
    cases = build_cases()
    assert len(cases) >= 100
    report = score_variants()
    assert report["cases"] == len(cases)
    assert report["false_auto_clear_rate"] == 0
    assert report["auto_clear_precision"] == 1
    assert report["auto_clear_recall"] == 1
    assert report["false_rejection_rate"] == 0
    kinds = set(report["kinds"])
    for kind in (
        "read_quality",
        "missing_document",
        "currency_mismatch",
        "price_mismatch",
        "quantity_mismatch",
        "partial_delivery",
        "total_mismatch",
        "tax_mismatch",
        "gstin_normalization",
        "vendor_mismatch",
        "duplicate_invoice",
        "potential_duplicate",
        "resubmission",
        "date_variation",
        "hindi",
        "mixed_language",
        "low_quality",
    ):
        assert kind in kinds
