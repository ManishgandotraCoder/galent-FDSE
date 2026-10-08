"""Print field accuracy, exception precision/recall, latency, and cost for the sample pack."""

from app.eval.harness import run_evaluation, write_report


def main() -> None:
    report = run_evaluation()
    path = write_report(report)
    precision = _percent(report["exception_precision"])
    recall = _percent(report["exception_recall"])
    accuracy = _percent(report["field_accuracy"])
    print(f"Wrote {path}")
    print(f"Documents processed:       {report['documents_processed']}")
    print(f"Field accuracy:            {accuracy}")
    print(f"Exception precision:       {precision}")
    print(f"Exception recall:          {recall}")
    print(f"Average latency:           {_duration(report['average_latency_ms'])}")
    print(f"P95 latency:               {_duration(report['p95_latency_ms'])}")
    print(f"Average tokens/document:   {report['average_tokens']:.0f}")
    print(f"Variant cases:             {report.get('variant_cases', 0)}")
    print(f"False auto-clear rate:     {_percent(report.get('false_auto_clear_rate'))}")
    print(f"Auto-clear precision:      {_percent(report.get('auto_clear_precision'))}")
    print(f"Auto-clear recall:         {_percent(report.get('auto_clear_recall'))}")
    print(f"False rejection rate:      {_percent(report.get('false_rejection_rate'))}")
    print(f"Human review rate:         {_percent(report.get('human_review_rate'))}")
    print()
    for bundle in report["bundles"]:
        mark = "ok" if bundle["expected_exceptions"] == bundle["predicted_exceptions"] else "DIFF"
        print(f"  [{mark}] {bundle['bundle_id']}: {bundle['predicted_exceptions']}")


def _duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} sec"


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


if __name__ == "__main__":
    main()
