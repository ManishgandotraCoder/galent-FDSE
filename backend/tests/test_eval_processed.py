from app.eval.harness import score_processed

LABEL = {
    "file": "02-inv.pdf",
    "presentation": "digital",
    "language": "en",
    "expected_validation": [],
    "document": {
        "document_type": "invoice",
        "document_number": "INV-1",
        "vendor": {"name": "Apex Steel"},
        "total": "10",
    },
}


def test_labelled_batch_is_scored_against_ground_truth():
    extraction = {
        "file_id": "file-1",
        "source_name": "02-inv.pdf",
        "confidence": 0.91,
        "extractor": "ollama:llama3.2",
        "document": LABEL["document"],
        "warnings": [],
        "input_tokens": 12,
        "output_tokens": 8,
    }
    report = score_processed(
        [extraction],
        latencies=[40],
        match={"status": "incomplete", "exceptions": ["missing_document"]},
        validation_issues=[],
        labels={"02-inv.pdf": LABEL},
        bundles=[
            {
                "id": "apex",
                "files": ["02-inv.pdf"],
                "expected_status": "incomplete",
                "expected_exceptions": ["missing_document"],
            }
        ],
    )
    assert report["documents_processed"] == 1
    assert report["field_accuracy"] == 1
    assert report["exception_precision"] == 1
    assert report["exception_recall"] == 1
    assert report["documents"][0]["latency_ms"] == 40
    assert report["documents"][0]["tokens"] == 20
    assert report["average_tokens"] == 20
    assert report["documents"][0]["presentation"] == "digital"
    assert report["bundles"][0]["predicted_exceptions"] == ["missing_document"]


def test_unlabelled_upload_keeps_operational_metrics_only():
    report = score_processed(
        [
            {
                "file_id": "file-1",
                "source_name": "notes.txt",
                "confidence": 0.4,
                "document": None,
                "warnings": ["No structured fields extracted."],
            }
        ],
        latencies=[15],
        match={"status": "incomplete", "exceptions": ["missing_document"]},
        validation_issues=[{"file_id": "file-1", "code": "extraction_failed"}],
        labels={},
        bundles=[],
    )
    assert report["field_accuracy"] is None
    assert report["exception_precision"] is None
    assert report["documents"][0]["document_id"] == "notes.txt"
    assert report["documents"][0]["field_total"] == 0
    assert report["documents"][0]["latency_ms"] == 15
    assert report["documents"][0]["tokens"] == 0
    assert report["average_tokens"] == 0
    assert report["bundles"] == []
