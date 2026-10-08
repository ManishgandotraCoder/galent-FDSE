import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from app.pipeline.normalize import normalize_extraction
from app.pipeline.parse import parse_read
from app.pipeline.read_text import read_bytes

ROOT = Path(__file__).resolve().parents[1] / "sample_data"


def test_layout_parser_matches_labelled_pdfs_offline():
    pack = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
    misses: list[str] = []
    for entry in pack["documents"]:
        if not entry["text_layer"]:
            continue
        path = ROOT / "documents" / entry["file"]
        read = read_bytes(path.read_bytes(), entry["file"])
        extraction = normalize_extraction(parse_read(entry["file"], entry["file"], read))
        if extraction.document is None:
            misses.append(f"{entry['file']}: no document ({extraction.warnings})")
            continue
        predicted = extraction.document.model_dump(mode="json")
        expected = entry["document"]
        for key in ("document_type", "document_number", "document_date", "currency", "subtotal", "tax", "total"):
            if not _same(expected.get(key), predicted.get(key)):
                misses.append(f"{entry['file']} {key}: {predicted.get(key)!r} != {expected.get(key)!r}")
        if expected["document_type"] != "purchase_order" and not _same(expected.get("po_number"), predicted.get("po_number")):
            misses.append(f"{entry['file']} po_number")
        if expected.get("received_by") and not _same(expected.get("received_by"), predicted.get("received_by")):
            misses.append(f"{entry['file']} received_by: {predicted.get('received_by')!r}")
        if not _same(expected["vendor"]["name"], predicted["vendor"]["name"]):
            misses.append(f"{entry['file']} vendor {predicted['vendor']['name']!r} != {expected['vendor']['name']!r}")
        if not _same(expected["vendor"].get("tax_id"), predicted["vendor"].get("tax_id")):
            misses.append(f"{entry['file']} tax id")
        if len(predicted["line_items"]) != len(expected["line_items"]):
            misses.append(f"{entry['file']} lines {len(predicted['line_items'])} != {len(expected['line_items'])}")
            continue
        for index, (got, want) in enumerate(zip(predicted["line_items"], expected["line_items"], strict=True)):
            for key in ("sku", "description", "quantity", "unit", "unit_price", "amount"):
                if not _same(want[key], got[key]):
                    misses.append(f"{entry['file']} line {index} {key}: {got[key]!r} != {want[key]!r}")
        assert extraction.confidence >= 0.95
    assert misses == []


def test_pdf_reader_keeps_each_page():
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "page one")
    pdf.showPage()
    pdf.drawString(72, 720, "page two")
    pdf.save()
    read = read_bytes(buffer.getvalue(), "note.pdf")
    assert len(read.pages) == 2
    assert "page one" in read.pages[0]
    assert "page two" in read.pages[1]
    assert "page one" in read.text and "page two" in read.text


def _same(expected, predicted) -> bool:
    if expected is None:
        return predicted is None
    try:
        return Decimal(str(expected)) == Decimal(str(predicted))
    except Exception:
        return str(expected).strip() == str(predicted).strip()
