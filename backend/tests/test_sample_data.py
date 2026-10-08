import json
from pathlib import Path

from app.pipeline.match import assess, three_way_match
from app.pipeline.parse import parse_read
from app.pipeline.read_text import read_bytes
from app.pipeline.validate import issues_for_extraction
from app.schemas.documents import Extraction, GoodsReceipt, Invoice, PurchaseOrder

ROOT = Path(__file__).resolve().parents[1] / "sample_data"
DOCUMENTS = ROOT / "documents"

MODELS = {
    "purchase_order": PurchaseOrder,
    "invoice": Invoice,
    "goods_receipt": GoodsReceipt,
}


def load_pack() -> dict:
    return json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))


def test_pack_contains_labelled_files():
    pack = load_pack()
    assert len(pack["documents"]) == 29
    names = [item["file"] for item in pack["documents"]]
    assert len(names) == len(set(names))
    assert sum(item["language"] == "hi-en" for item in pack["documents"]) == 1
    assert sum(item["presentation"] == "scan" for item in pack["documents"]) == 7
    assert sum(not item["text_layer"] for item in pack["documents"]) == 7

    for item in pack["documents"]:
        path = DOCUMENTS / item["file"]
        assert path.is_file()
        assert path.stat().st_size > 1000
        signature = path.read_bytes()[:4]
        if path.suffix == ".pdf":
            assert signature == b"%PDF"
            assert item["text_layer"] is True
        else:
            assert signature[:2] == b"\xff\xd8"
            assert item["text_layer"] is False
        MODELS[item["document"]["document_type"]].model_validate(item["document"])


def test_planted_errors_match_the_labels():
    pack = load_pack()
    by_file = {item["file"]: item for item in pack["documents"]}
    invoice_numbers = [item["document"]["document_number"] for item in pack["documents"] if item["document"]["document_type"] == "invoice"]
    assert invoice_numbers.count("INV-77821") == 2

    for bundle in pack["bundles"]:
        extractions = []
        for filename in bundle["files"]:
            entry = by_file[filename]
            parsed = MODELS[entry["document"]["document_type"]].model_validate(entry["document"])
            extraction = Extraction(
                file_id=filename,
                document_type=parsed.document_type,
                confidence=0.95,
                document=parsed,
            )
            extractions.append(extraction)
            issues = [issue.code for issue in issues_for_extraction(extraction)]
            assert issues == entry["expected_validation"]
        matched = three_way_match(extractions)
        assert matched.status == bundle["expected_status"]
        assert matched.exceptions == bundle["expected_exceptions"]
        if bundle.get("expected_routing") is None:
            continue
        scored = [
            item.model_copy(update={"confidence": bundle["extraction_confidence"], "completeness": 1.0})
            for item in extractions
        ]
        routed = assess(scored, matched, [], auto_clear=0.95, flag=0.70)
        assert routed.routing == bundle["expected_routing"]
        assert routed.scores.routing_score == bundle["extraction_confidence"]


def test_success_edges_read_at_100_and_95_percent():
    pack = load_pack()
    expected = {
        "21-po-24040-orion-castings.pdf": 1.0,
        "22-inv-10040-orion-castings.pdf": 1.0,
        "23-grn-31040-orion-castings.pdf": 1.0,
        "24-po-24041-shakti-gaskets.pdf": 0.95,
        "25-inv-10041-shakti-gaskets.pdf": 0.95,
        "26-grn-31041-shakti-gaskets.pdf": 0.95,
    }
    by_file = {item["file"]: item for item in pack["documents"]}
    for filename, confidence in expected.items():
        path = DOCUMENTS / filename
        extraction = parse_read(filename, filename, read_bytes(path.read_bytes(), filename))
        assert extraction.document is not None, extraction.warnings
        assert extraction.confidence == confidence
        assert extraction.document.document_date is None or confidence == 1.0
        labelled = by_file[filename]["document"]
        assert extraction.document.document_number == labelled["document_number"]
