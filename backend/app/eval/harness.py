"""Run the labelled sample pack through extraction and matching."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.config import BACKEND_ROOT, get_settings
from app.eval.metrics import exception_counts, field_counts, percentile, ratio
from app.eval.variants import score_variants
from app.pipeline.extract import extract_bytes
from app.pipeline.match import three_way_match
from app.pipeline.normalize import normalize_extraction
from app.pipeline.validate import issues_for_extraction
from app.schemas.documents import Extraction

SAMPLE_DIR = BACKEND_ROOT / "sample_data"
REPORT_PATH = BACKEND_ROOT / "eval_report.json"


def run_evaluation(sample_dir: Path | None = None) -> dict:
    root = sample_dir or SAMPLE_DIR
    pack = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
    extracted: dict[str, tuple[Extraction, int]] = {}
    document_rows = []
    field_correct = 0
    field_total = 0
    validation_pairs: list[tuple[list[str], list[str]]] = []

    for entry in pack["documents"]:
        path = root / "documents" / entry["file"]
        started = time.perf_counter()
        extraction = normalize_extraction(extract_bytes(entry["file"], path.read_bytes(), source_name=entry["file"]))
        latency_ms = int((time.perf_counter() - started) * 1000)
        extracted[entry["file"]] = (extraction, latency_ms)
        predicted = extraction.document.model_dump(mode="json") if extraction.document else None
        correct, total = field_counts(entry["document"], predicted)
        field_correct += correct
        field_total += total
        validation = [issue.code for issue in issues_for_extraction(extraction)]
        validation_pairs.append((list(entry["expected_validation"]), validation))
        document_rows.append(
            {
                "document_id": entry["file"],
                "presentation": entry["presentation"],
                "language": entry["language"],
                "extractor": extraction.extractor,
                "field_correct": correct,
                "field_total": total,
                "field_accuracy": ratio(correct, total),
                "expected_validation": entry["expected_validation"],
                "predicted_validation": validation,
                "confidence": extraction.confidence,
                "latency_ms": latency_ms,
                "input_tokens": extraction.input_tokens,
                "output_tokens": extraction.output_tokens,
                "tokens": extraction.input_tokens + extraction.output_tokens,
                "warnings": extraction.warnings,
            }
        )

    bundle_rows = []
    bundle_pairs: list[tuple[list[str], list[str]]] = []
    for bundle in pack["bundles"]:
        extractions = [extracted[name][0] for name in bundle["files"]]
        matched = three_way_match(extractions)
        bundle_pairs.append((list(bundle["expected_exceptions"]), list(matched.exceptions)))
        bundle_rows.append(
            {
                "bundle_id": bundle["id"],
                "files": bundle["files"],
                "expected_status": bundle["expected_status"],
                "predicted_status": matched.status,
                "expected_exceptions": bundle["expected_exceptions"],
                "predicted_exceptions": matched.exceptions,
            }
        )

    true_positive, false_positive, false_negative = exception_counts(bundle_pairs)
    validation_tp, validation_fp, validation_fn = exception_counts(validation_pairs)
    latencies = [row["latency_ms"] for row in document_rows]
    token_counts = [row["tokens"] for row in document_rows]
    settings = get_settings()
    report = {
        "documents_processed": len(document_rows),
        "field_correct": field_correct,
        "field_total": field_total,
        "field_accuracy": ratio(field_correct, field_total),
        "exception_true_positive": true_positive,
        "exception_false_positive": false_positive,
        "exception_false_negative": false_negative,
        "exception_precision": ratio(true_positive, true_positive + false_positive),
        "exception_recall": ratio(true_positive, true_positive + false_negative),
        "validation_precision": ratio(validation_tp, validation_tp + validation_fp),
        "validation_recall": ratio(validation_tp, validation_tp + validation_fn),
        "average_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "average_tokens": (sum(token_counts) / len(token_counts)) if token_counts else 0,
        "auto_clear_confidence": settings.auto_clear_confidence,
        "flag_confidence": settings.flag_confidence,
        "documents": document_rows,
        "bundles": bundle_rows,
    }
    routing = score_variants()
    report["variant_cases"] = routing["cases"]
    report["false_auto_clear_rate"] = routing["false_auto_clear_rate"]
    report["auto_clear_precision"] = routing["auto_clear_precision"]
    report["auto_clear_recall"] = routing["auto_clear_recall"]
    report["false_rejection_rate"] = routing["false_rejection_rate"]
    report["human_review_rate"] = routing["human_review_rate"]
    report["variant_exception_precision"] = routing["exception_precision"]
    report["variant_exception_recall"] = routing["exception_recall"]
    return report


def write_report(report: dict, path: Path | None = None) -> Path:
    destination = path or REPORT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return destination


def live_report_path() -> Path:
    return get_settings().data_dir / "eval_report.json"


def publish_processed(
    extractions: list[dict],
    latencies: list[int] | None = None,
    match: dict | None = None,
    validation_issues: list[dict] | None = None,
) -> dict:
    """Score one finished batch and write the report the evaluation page reads."""
    report = score_processed(extractions, latencies=latencies, match=match, validation_issues=validation_issues)
    write_report(report, live_report_path())
    return report


def score_processed(
    extractions: list[dict],
    *,
    latencies: list[int] | None = None,
    match: dict | None = None,
    validation_issues: list[dict] | None = None,
    labels: dict[str, dict] | None = None,
    bundles: list[dict] | None = None,
) -> dict:
    if labels is None:
        label_rows, bundle_rows_in = _load_labels()
    else:
        label_rows = labels
        bundle_rows_in = list(bundles or [])
    timings = list(latencies or [])
    issues = list(validation_issues or [])
    document_rows = []
    field_correct = 0
    field_total = 0
    validation_pairs: list[tuple[list[str], list[str]]] = []

    for index, extraction in enumerate(extractions):
        if not isinstance(extraction, dict):
            continue
        name = _document_name(extraction)
        label = label_rows.get(name)
        predicted = extraction.get("document") if isinstance(extraction.get("document"), dict) else None
        expected_validation = list(label["expected_validation"]) if label else []
        predicted_validation = [
            issue["code"]
            for issue in issues
            if isinstance(issue, dict) and issue.get("file_id") == extraction.get("file_id") and issue.get("code")
        ]
        if label:
            correct, total = field_counts(label.get("document"), predicted)
            field_correct += correct
            field_total += total
            validation_pairs.append((expected_validation, predicted_validation))
            accuracy = ratio(correct, total)
            presentation = label.get("presentation") or "uploaded"
            language = label.get("language") or "unlabelled"
        else:
            correct, total = 0, 0
            accuracy = None
            presentation = "uploaded"
            language = "unlabelled"
        document_rows.append(
            {
                "document_id": name,
                "file_id": extraction.get("file_id"),
                "presentation": presentation,
                "language": language,
                "extractor": extraction.get("extractor"),
                "field_correct": correct,
                "field_total": total,
                "field_accuracy": accuracy,
                "expected_validation": expected_validation,
                "predicted_validation": predicted_validation,
                "confidence": float(extraction.get("confidence") or 0),
                "latency_ms": int(timings[index]) if index < len(timings) else 0,
                "input_tokens": int(extraction.get("input_tokens") or 0),
                "output_tokens": int(extraction.get("output_tokens") or 0),
                "tokens": int(extraction.get("input_tokens") or 0) + int(extraction.get("output_tokens") or 0),
                "warnings": list(extraction.get("warnings") or []),
            }
        )

    predicted_status = match.get("status") if isinstance(match, dict) and match.get("status") else "incomplete"
    predicted_exceptions = list(match.get("exceptions") or []) if isinstance(match, dict) else []
    names = [row["document_id"] for row in document_rows]
    bundle_rows = []
    bundle_pairs: list[tuple[list[str], list[str]]] = []
    for bundle in bundle_rows_in:
        if sorted(bundle.get("files") or []) != sorted(names):
            continue
        expected_exceptions = list(bundle.get("expected_exceptions") or [])
        bundle_pairs.append((expected_exceptions, predicted_exceptions))
        bundle_rows.append(
            {
                "bundle_id": bundle.get("id") or "processed",
                "files": list(bundle.get("files") or []),
                "expected_status": bundle.get("expected_status"),
                "predicted_status": predicted_status,
                "expected_exceptions": expected_exceptions,
                "predicted_exceptions": predicted_exceptions,
            }
        )

    true_positive, false_positive, false_negative = exception_counts(bundle_pairs)
    validation_tp, validation_fp, validation_fn = exception_counts(validation_pairs)
    latencies_ms = [row["latency_ms"] for row in document_rows]
    token_counts = [row["tokens"] for row in document_rows]
    settings = get_settings()
    return {
        "documents_processed": len(document_rows),
        "field_correct": field_correct,
        "field_total": field_total,
        "field_accuracy": ratio(field_correct, field_total),
        "exception_true_positive": true_positive,
        "exception_false_positive": false_positive,
        "exception_false_negative": false_negative,
        "exception_precision": ratio(true_positive, true_positive + false_positive),
        "exception_recall": ratio(true_positive, true_positive + false_negative),
        "validation_precision": ratio(validation_tp, validation_tp + validation_fp),
        "validation_recall": ratio(validation_tp, validation_tp + validation_fn),
        "average_latency_ms": (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0,
        "p95_latency_ms": percentile(latencies_ms, 0.95),
        "average_tokens": (sum(token_counts) / len(token_counts)) if token_counts else 0,
        "auto_clear_confidence": settings.auto_clear_confidence,
        "flag_confidence": settings.flag_confidence,
        "documents": document_rows,
        "bundles": bundle_rows,
    }


def case_report() -> dict | None:
    """Score the cases on the desk. Nothing is filled in from the sample pack."""
    from app.pipeline.graph import graph_state
    from app.services.run_store import list_runs

    summaries = list_runs()
    if not summaries:
        return None

    labels, bundles = _load_labels()
    document_rows: list[dict] = []
    bundle_rows: list[dict] = []
    seen_files: set[str] = set()
    seen_bundles: set[str] = set()

    for summary in summaries:
        snapshot = graph_state({"configurable": {"thread_id": summary.id}})
        values = getattr(snapshot, "values", None) or {}
        if not values:
            continue
        extractions = [item for item in values.get("extractions") or [] if isinstance(item, dict)]
        part = score_processed(
            extractions,
            latencies=list(values.get("document_latencies") or []),
            match=values.get("match") if isinstance(values.get("match"), dict) else None,
            validation_issues=list(values.get("validation_issues") or []),
            labels=labels,
            bundles=bundles,
        )
        for row in part["documents"]:
            key = str(row.get("file_id") or row["document_id"])
            if key in seen_files:
                continue
            seen_files.add(key)
            document_rows.append(row)
        for bundle in part["bundles"]:
            bundle_id = str(bundle.get("bundle_id") or "")
            if bundle_id in seen_bundles:
                continue
            seen_bundles.add(bundle_id)
            bundle_rows.append(bundle)

    field_correct = sum(int(row["field_correct"]) for row in document_rows)
    field_total = sum(int(row["field_total"]) for row in document_rows)
    bundle_pairs = [
        (list(bundle["expected_exceptions"]), list(bundle["predicted_exceptions"])) for bundle in bundle_rows
    ]
    true_positive, false_positive, false_negative = exception_counts(bundle_pairs)
    latencies_ms = [int(row["latency_ms"]) for row in document_rows]
    token_counts = [int(row["tokens"]) for row in document_rows]
    confidences = [item.confidence for item in summaries if item.confidence is not None]
    settings = get_settings()
    return {
        "documents_processed": len(document_rows),
        "cases": len(summaries),
        "auto_cleared": sum(1 for item in summaries if item.routing == "auto_clear"),
        "needs_review": sum(1 for item in summaries if item.routing == "flag"),
        "rejected": sum(1 for item in summaries if item.routing == "reject"),
        "average_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "field_correct": field_correct,
        "field_total": field_total,
        "field_accuracy": ratio(field_correct, field_total),
        "exception_true_positive": true_positive,
        "exception_false_positive": false_positive,
        "exception_false_negative": false_negative,
        "exception_precision": ratio(true_positive, true_positive + false_positive),
        "exception_recall": ratio(true_positive, true_positive + false_negative),
        "average_latency_ms": (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0,
        "p95_latency_ms": percentile(latencies_ms, 0.95),
        "average_tokens": (sum(token_counts) / len(token_counts)) if token_counts else 0,
        "auto_clear_confidence": settings.auto_clear_confidence,
        "flag_confidence": settings.flag_confidence,
        "documents": document_rows,
        "bundles": bundle_rows,
    }


def _load_labels() -> tuple[dict[str, dict], list[dict]]:
    path = SAMPLE_DIR / "ground_truth.json"
    if not path.is_file():
        return {}, []
    pack = json.loads(path.read_text(encoding="utf-8"))
    documents = {
        entry["file"]: entry
        for entry in pack.get("documents") or []
        if isinstance(entry, dict) and entry.get("file")
    }
    bundles = [bundle for bundle in pack.get("bundles") or [] if isinstance(bundle, dict)]
    return documents, bundles


def _document_name(extraction: dict) -> str:
    raw = extraction.get("source_name") or extraction.get("file_id") or "document"
    return Path(str(raw)).name
