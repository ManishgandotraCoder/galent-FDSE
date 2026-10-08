from decimal import Decimal

from app.pipeline.parse_layout import parse_ocr_tokens
from app.pipeline.read_text import OcrToken


def token(text: str, xmin: float, ymin: float, xmax: float, ymax: float) -> OcrToken:
    return OcrToken(text=text, confidence=1, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)


def test_skewed_scan_keeps_row_numbers_out_of_the_sku_and_pairs_totals_in_order():
    tokens = [
        token("TAX INVOICE", 0.66, 0.90, 0.77, 0.93),
        token("SUPPLIER", 0.44, 0.81, 0.50, 0.83),
        token("Bharat Bearings Pvt Ltd", 0.44, 0.79, 0.57, 0.81),
        token("E-22, Bhosari MIDC, Pune 411026", 0.44, 0.77, 0.63, 0.79),
        token("GSTIN 27AABCB3344C1Z6", 0.44, 0.75, 0.60, 0.77),
        token("DOCUMENT NO", 0.07, 0.72, 0.15, 0.73),
        token("INV-88044", 0.07, 0.70, 0.14, 0.72),
        token("PO NUMBER", 0.54, 0.73, 0.61, 0.75),
        token("PO-24019", 0.54, 0.71, 0.61, 0.73),
        token("DATE", 0.30, 0.73, 0.34, 0.74),
        token("16 Sep 2026", 0.30, 0.71, 0.39, 0.73),
        token("SKU", 0.11, 0.66, 0.14, 0.68),
        token("Description", 0.20, 0.66, 0.27, 0.68),
        token("Qty", 0.47, 0.67, 0.50, 0.69),
        token("Unit", 0.53, 0.67, 0.56, 0.69),
        token("Rate", 0.59, 0.67, 0.62, 0.70),
        token("Amount", 0.68, 0.68, 0.73, 0.70),
        token("1", 0.08, 0.64, 0.09, 0.66),
        token("BRG-6205", 0.11, 0.64, 0.17, 0.66),
        token("Deep groove ball bearing 6205", 0.20, 0.64, 0.36, 0.67),
        token("100", 0.47, 0.65, 0.50, 0.67),
        token("nos", 0.53, 0.65, 0.56, 0.67),
        token("Rs. 340.00", 0.59, 0.65, 0.65, 0.68),
        token("Rs. 34.000.00", 0.68, 0.66, 0.76, 0.68),
        token("2", 0.08, 0.62, 0.10, 0.63),
        token("BRG-H-6205", 0.12, 0.62, 0.18, 0.63),
        token("Bearing housing 6205", 0.20, 0.62, 0.32, 0.64),
        token("100", 0.47, 0.63, 0.50, 0.65),
        token("nos", 0.54, 0.63, 0.56, 0.65),
        token("Rs. 95.00", 0.59, 0.63, 0.65, 0.65),
        token("Rs. 9,500.00", 0.69, 0.64, 0.75, 0.66),
        token("Subtotal", 0.54, 0.598, 0.59, 0.612),
        token("CGST 9%", 0.54, 0.582, 0.62, 0.596),
        token("SGST 9%", 0.54, 0.565, 0.62, 0.579),
        token("Total", 0.54, 0.548, 0.58, 0.561),
        token("Rs. 43,500.00", 0.71, 0.606, 0.80, 0.619),
        token("Rs. 3,915.00", 0.72, 0.586, 0.80, 0.603),
        token("Rs. 3,915.00", 0.72, 0.571, 0.80, 0.585),
        token("Rs. 51,330.00", 0.72, 0.554, 0.80, 0.570),
    ]
    document, warnings = parse_ocr_tokens(tokens)
    assert warnings == []
    assert document is not None
    assert document.document_type == "invoice"
    assert document.document_number == "INV-88044"
    assert document.po_number == "PO-24019"
    assert document.vendor.name == "Bharat Bearings Pvt Ltd"
    assert document.vendor.tax_id == "27AABCB3344C1Z6"
    assert [line.sku for line in document.line_items] == ["BRG-6205", "BRG-H-6205"]
    assert document.line_items[0].amount == Decimal("34000.00")
    assert document.subtotal == Decimal("43500.00")
    assert document.tax == Decimal("7830.00")
    assert document.total == Decimal("51330.00")
