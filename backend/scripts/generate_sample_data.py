"""Write the labelled AP sample pack under backend/sample_data/.

The pack is for a fictional buyer, Northwind Fabrication. Clean trios match.
Three of them are success edges: a complete digital read at 100%, a digital
read with no issue date at 95%, and a straight photograph of a clean trio at
90%. The other files plant the errors the brief asks for: a wrong invoice
total, a duplicate invoice number, a legal-name variant, a genuinely different
vendor, a partial delivery, skewed scans, and one mixed Hindi-English invoice
that exists only as a photograph.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.pipeline.match import assess, three_way_match  # noqa: E402
from app.pipeline.validate import issues_for_extraction  # noqa: E402
from app.schemas.documents import (  # noqa: E402
    Extraction,
    GoodsReceipt,
    Invoice,
    LineItem,
    Party,
    PurchaseOrder,
)

OUTPUT_DIR = BACKEND_ROOT / "sample_data"
DOCUMENT_DIR = OUTPUT_DIR / "documents"
HINDI_FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
PAGE_W, PAGE_H = A4
MARGIN = 36

BUYER = {
    "name": "Northwind Fabrication Pvt Ltd",
    "address": "Plot 18, MIDC Bhosari, Pune 411026",
    "tax_id": "27AABCN1234F1Z5",
}

NAVY = HexColor("#1B3A4B")
TEAL = HexColor("#2F6F6A")
INK = HexColor("#1C2430")
MUTED = HexColor("#5C6B7A")
LINE = HexColor("#D5DDE4")
PAPER = HexColor("#F4F7F8")
AMBER = HexColor("#C9852A")


@dataclass
class Item:
    sku: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


@dataclass
class SampleDoc:
    filename: str
    kind: str
    number: str
    issued: date
    vendor_name: str
    vendor_address: str
    vendor_tax_id: str
    lines: list[Item]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    po_number: str | None = None
    received_by: str | None = None
    gate_entry: str | None = None
    vehicle: str | None = None
    remarks: str | None = None
    footer_note: str | None = None
    language: str = "en"
    presentation: str = "digital"
    planted_error: str | None = None
    alternate_of: str | None = None
    expected_validation: list[str] = field(default_factory=list)
    text_layer: bool = True
    show_date: bool = True


@dataclass
class Bundle:
    id: str
    files: list[str]
    expected_status: str
    expected_exceptions: list[str]
    summary: str
    expected_routing: str | None = None
    extraction_confidence: float | None = None


def item(sku: str, description: str, quantity: str, unit: str, unit_price: str) -> Item:
    return Item(sku, description, Decimal(quantity), unit, Decimal(unit_price))


def tax_total(lines: list[Item], rate: str = "0.18") -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum((line.amount for line in lines), Decimal("0"))
    tax = (subtotal * Decimal(rate)).quantize(Decimal("0.01"))
    return subtotal, tax, subtotal + tax


def catalog():
    apex_lines = [
        item("MS-PL-10", "MS plate 10mm", "40", "sheet", "2450"),
        item("WE-6013", "Welding electrode E6013", "20", "kg", "180"),
    ]
    apex_sub, apex_tax, apex_total = tax_total(apex_lines)
    apex_vendor = ("Apex Steel Traders", "Shop 4, Mundhwa Industrial Area, Pune 411036", "27AABCA1122B1Z8")

    bearing = item("BRG-6205", "Deep groove ball bearing 6205", "100", "nos", "340")
    housing = item("BRG-H-6205", "Bearing housing 6205", "100", "nos", "95")
    ordered = [bearing, housing]
    order_sub, order_tax, order_total = tax_total(ordered)
    received = [
        item("BRG-6205", "Deep groove ball bearing 6205", "60", "nos", "340"),
        housing,
    ]
    received_sub = sum((line.amount for line in received), Decimal("0"))
    bharat = ("Bharat Bearings Pvt Ltd", "E-22, Bhosari MIDC, Pune 411026", "27AABCB3344C1Z6")

    fastener_lines = [
        item("HX-M10", "Hex bolt M10 x 40", "500", "nos", "12.50"),
        item("NY-M10", "Nyloc nut M10", "500", "nos", "4.00"),
    ]
    fast_sub, fast_tax, fast_total = tax_total(fastener_lines)
    lakshmi = ("Lakshmi Fasteners", "Gala 7, Taloja MIDC, Navi Mumbai 410208", "27AABCL7788D1Z4")

    hose = [item("HH-12", "Hydraulic hose 1/2 inch", "25", "mtr", "860")]
    hose_sub, hose_tax, hose_total = tax_total(hose)
    acme_address = "14, Industrial Estate, Hadapsar, Pune 411013"
    acme_tax = "27AABCA9988A1Z1"

    pump = [item("HP-220", "Hydraulic gear pump", "4", "nos", "18750")]
    pump_sub, pump_tax, pump_total = tax_total(pump)
    western = ("Western Hydraulics Ltd", "Survey 42, Chinchwad, Pune 411019", "27AABCW4455C1Z2")
    deccan = ("Deccan Hydraulics", "Plot 9, Peenya 2nd Stage, Bengaluru 560058", "29AADCD5566H1Z7")

    hindi_lines = [
        item("CD-4", "काटने की डिस्क 4 इंच / Cutting disc 4 inch", "200", "nos", "45"),
        item("SG-L", "सुरक्षा दस्ताने / Safety gloves", "50", "pair", "120"),
    ]
    hindi_sub, hindi_tax, hindi_total = tax_total(hindi_lines)

    orion_lines = [item("CI-80", "Cast iron block 80mm", "12", "nos", "3200")]
    orion_sub, orion_tax, orion_total = tax_total(orion_lines)
    orion = ("Orion Castings Pvt Ltd", "Plot 6, Chakan Industrial Area, Pune 410501", "27AABCO2211F1Z3")

    shakti_lines = [item("GK-150", "Spiral wound gasket 150mm", "80", "nos", "210")]
    shakti_sub, shakti_tax, shakti_total = tax_total(shakti_lines)
    shakti = ("Shakti Gaskets", "Unit 3, Ranjangaon MIDC, Pune 412220", "27AABCS8899G1Z2")

    metro_lines = [item("PP-25", "Polypropylene sheet 25mm", "30", "sheet", "640")]
    metro_sub, metro_tax, metro_total = tax_total(metro_lines)
    metro = ("Metro Polymers", "Shed 11, Pirangut Industrial Area, Pune 412115", "27AABCM4455H1Z8")

    documents = [
        SampleDoc(
            "01-po-24018-apex-steel.pdf",
            "purchase_order",
            "PO-24018",
            date(2026, 9, 2),
            *apex_vendor,
            apex_lines,
            apex_sub,
            apex_tax,
            apex_total,
        ),
        SampleDoc(
            "02-inv-77821-apex-steel.pdf",
            "invoice",
            "INV-77821",
            date(2026, 9, 10),
            *apex_vendor,
            apex_lines,
            apex_sub,
            apex_tax,
            apex_total,
            po_number="PO-24018",
        ),
        SampleDoc(
            "03-grn-31018-apex-steel.pdf",
            "goods_receipt",
            "GRN-31018",
            date(2026, 9, 9),
            *apex_vendor,
            apex_lines,
            apex_sub,
            apex_tax,
            apex_total,
            po_number="PO-24018",
            received_by="R. Kulkarni",
            gate_entry="GE-4418",
            vehicle="MH12 JQ 2281",
        ),
        SampleDoc(
            "04-po-24019-bharat-bearings.pdf",
            "purchase_order",
            "PO-24019",
            date(2026, 9, 4),
            *bharat,
            ordered,
            order_sub,
            order_tax,
            order_total,
        ),
        SampleDoc(
            "05-inv-88044-bharat-bearings.pdf",
            "invoice",
            "INV-88044",
            date(2026, 9, 16),
            *bharat,
            ordered,
            order_sub,
            order_tax,
            order_total,
            po_number="PO-24019",
            planted_error="partial_delivery",
        ),
        SampleDoc(
            "06-grn-31019-bharat-bearings.pdf",
            "goods_receipt",
            "GRN-31019",
            date(2026, 9, 15),
            *bharat,
            received,
            received_sub,
            Decimal("0"),
            received_sub,
            po_number="PO-24019",
            received_by="S. Patil",
            gate_entry="GE-4490",
            vehicle="MH14 RT 9012",
            remarks="Short receipt. 40 nos of BRG-6205 still pending.",
            planted_error="partial_delivery",
        ),
        SampleDoc(
            "07-po-24020-lakshmi-fasteners.pdf",
            "purchase_order",
            "PO-24020",
            date(2026, 9, 5),
            *lakshmi,
            fastener_lines,
            fast_sub,
            fast_tax,
            fast_total,
        ),
        SampleDoc(
            "08-inv-99107-lakshmi-fasteners.pdf",
            "invoice",
            "INV-99107",
            date(2026, 9, 14),
            *lakshmi,
            fastener_lines,
            fast_sub,
            fast_tax,
            Decimal("9375.00"),
            po_number="PO-24020",
            planted_error="wrong_total",
            expected_validation=["total_mismatch"],
        ),
        SampleDoc(
            "09-grn-31020-lakshmi-fasteners.pdf",
            "goods_receipt",
            "GRN-31020",
            date(2026, 9, 12),
            *lakshmi,
            fastener_lines,
            fast_sub,
            fast_tax,
            fast_total,
            po_number="PO-24020",
            received_by="A. Shaikh",
            gate_entry="GE-4502",
            vehicle="MH43 B 1184",
        ),
        SampleDoc(
            "10-po-24021-acme-pvt.pdf",
            "purchase_order",
            "PO-24021",
            date(2026, 9, 8),
            "Acme Pvt Ltd",
            acme_address,
            acme_tax,
            hose,
            hose_sub,
            hose_tax,
            hose_total,
        ),
        SampleDoc(
            "11-inv-77890-acme-private.pdf",
            "invoice",
            "INV-77890",
            date(2026, 9, 19),
            "ACME Private Limited",
            acme_address,
            acme_tax,
            hose,
            hose_sub,
            hose_tax,
            hose_total,
            po_number="PO-24021",
            planted_error="vendor_name_variant",
        ),
        SampleDoc(
            "12-grn-31021-acme-pvt.pdf",
            "goods_receipt",
            "GRN-31021",
            date(2026, 9, 18),
            "Acme Pvt Ltd",
            acme_address,
            acme_tax,
            hose,
            hose_sub,
            hose_tax,
            hose_total,
            po_number="PO-24021",
            received_by="M. Deshmukh",
            gate_entry="GE-4518",
            vehicle="MH12 AB 4401",
        ),
        SampleDoc(
            "13-po-24022-western-hydraulics.pdf",
            "purchase_order",
            "PO-24022",
            date(2026, 9, 3),
            *western,
            pump,
            pump_sub,
            pump_tax,
            pump_total,
        ),
        SampleDoc(
            "14-inv-44210-deccan-hydraulics.pdf",
            "invoice",
            "INV-44210",
            date(2026, 9, 18),
            *deccan,
            pump,
            pump_sub,
            pump_tax,
            pump_total,
            po_number="PO-24022",
            planted_error="different_vendor",
        ),
        SampleDoc(
            "15-grn-31022-western-hydraulics.pdf",
            "goods_receipt",
            "GRN-31022",
            date(2026, 9, 17),
            *western,
            pump,
            pump_sub,
            pump_tax,
            pump_total,
            po_number="PO-24022",
            received_by="P. Jadhav",
            gate_entry="GE-4524",
            vehicle="MH14 K 7730",
        ),
        SampleDoc(
            "16-inv-77821-apex-resubmit.pdf",
            "invoice",
            "INV-77821",
            date(2026, 9, 10),
            *apex_vendor,
            apex_lines,
            apex_sub,
            apex_tax,
            apex_total,
            po_number="PO-24018",
            footer_note="Duplicate copy",
            planted_error="duplicate_invoice_number",
        ),
        SampleDoc(
            "21-po-24040-orion-castings.pdf",
            "purchase_order",
            "PO-24040",
            date(2026, 9, 6),
            *orion,
            orion_lines,
            orion_sub,
            orion_tax,
            orion_total,
        ),
        SampleDoc(
            "22-inv-10040-orion-castings.pdf",
            "invoice",
            "INV-10040",
            date(2026, 9, 11),
            *orion,
            orion_lines,
            orion_sub,
            orion_tax,
            orion_total,
            po_number="PO-24040",
        ),
        SampleDoc(
            "23-grn-31040-orion-castings.pdf",
            "goods_receipt",
            "GRN-31040",
            date(2026, 9, 11),
            *orion,
            orion_lines,
            orion_sub,
            orion_tax,
            orion_total,
            po_number="PO-24040",
            received_by="N. Bhosale",
            gate_entry="GE-4601",
            vehicle="MH12 CD 1001",
        ),
        SampleDoc(
            "24-po-24041-shakti-gaskets.pdf",
            "purchase_order",
            "PO-24041",
            date(2026, 9, 7),
            *shakti,
            shakti_lines,
            shakti_sub,
            shakti_tax,
            shakti_total,
            show_date=False,
        ),
        SampleDoc(
            "25-inv-10041-shakti-gaskets.pdf",
            "invoice",
            "INV-10041",
            date(2026, 9, 13),
            *shakti,
            shakti_lines,
            shakti_sub,
            shakti_tax,
            shakti_total,
            po_number="PO-24041",
            show_date=False,
        ),
        SampleDoc(
            "26-grn-31041-shakti-gaskets.pdf",
            "goods_receipt",
            "GRN-31041",
            date(2026, 9, 13),
            *shakti,
            shakti_lines,
            shakti_sub,
            shakti_tax,
            shakti_total,
            po_number="PO-24041",
            received_by="K. More",
            gate_entry="GE-4608",
            vehicle="MH14 EF 2295",
            show_date=False,
        ),
    ]

    scans = [
        ("17-inv-88044-bharat-scan.jpg", "05-inv-88044-bharat-bearings.pdf", 2.4, 0.035, 62),
        ("18-grn-31019-bharat-scan.jpg", "06-grn-31019-bharat-bearings.pdf", -3.1, -0.03, 56),
        ("19-po-24020-lakshmi-scan.jpg", "07-po-24020-lakshmi-fasteners.pdf", 3.8, 0.045, 52),
    ]

    bundles = [
        Bundle(
            "apex-steel-clean",
            [
                "01-po-24018-apex-steel.pdf",
                "02-inv-77821-apex-steel.pdf",
                "03-grn-31018-apex-steel.pdf",
            ],
            "matched",
            [],
            "PO, invoice, and goods receipt agree on vendor, price, and quantity.",
        ),
        Bundle(
            "bharat-partial-delivery",
            [
                "04-po-24019-bharat-bearings.pdf",
                "05-inv-88044-bharat-bearings.pdf",
                "06-grn-31019-bharat-bearings.pdf",
            ],
            "exception",
            ["quantity_mismatch", "partial_delivery"],
            "Ordered 100 bearings, warehouse received 60, invoice bills 100.",
        ),
        Bundle(
            "lakshmi-wrong-total",
            [
                "07-po-24020-lakshmi-fasteners.pdf",
                "08-inv-99107-lakshmi-fasteners.pdf",
                "09-grn-31020-lakshmi-fasteners.pdf",
            ],
            "exception",
            ["total_mismatch"],
            "Invoice lines plus GST equal Rs. 9,735.00. The printed total is Rs. 9,375.00.",
        ),
        Bundle(
            "acme-legal-name",
            [
                "10-po-24021-acme-pvt.pdf",
                "11-inv-77890-acme-private.pdf",
                "12-grn-31021-acme-pvt.pdf",
            ],
            "matched",
            [],
            'PO and GRN say "Acme Pvt Ltd". The invoice says "ACME Private Limited". The GSTIN matches, so the legal-form difference is normalized.',
        ),
        Bundle(
            "western-different-vendor",
            [
                "13-po-24022-western-hydraulics.pdf",
                "14-inv-44210-deccan-hydraulics.pdf",
                "15-grn-31022-western-hydraulics.pdf",
            ],
            "exception",
            ["vendor_mismatch"],
            "Goods were ordered from Western Hydraulics Ltd and received from them. The bill is from Deccan Hydraulics.",
        ),
        Bundle(
            "apex-duplicate-invoice",
            [
                "01-po-24018-apex-steel.pdf",
                "02-inv-77821-apex-steel.pdf",
                "03-grn-31018-apex-steel.pdf",
                "16-inv-77821-apex-resubmit.pdf",
            ],
            "exception",
            ["duplicate_invoice"],
            "INV-77821 is submitted twice. The purchase order, the first invoice, and the goods receipt still agree.",
        ),
        Bundle(
            "gupta-hindi-unpaired",
            ["20-inv-5520-gupta-hindi.jpg"],
            "incomplete",
            ["missing_document"],
            "Mixed Hindi-English invoice with no purchase order or goods receipt in the pack.",
        ),
        Bundle(
            "success-100-orion",
            [
                "21-po-24040-orion-castings.pdf",
                "22-inv-10040-orion-castings.pdf",
                "23-grn-31040-orion-castings.pdf",
            ],
            "matched",
            [],
            "Digital purchase order, invoice, and goods receipt agree, and every field including the issue date is printed. Upload these three files together. The read is 100% and the case auto-clears.",
            expected_routing="auto_clear",
            extraction_confidence=1.0,
        ),
        Bundle(
            "success-95-shakti",
            [
                "24-po-24041-shakti-gaskets.pdf",
                "25-inv-10041-shakti-gaskets.pdf",
                "26-grn-31041-shakti-gaskets.pdf",
            ],
            "matched",
            [],
            "Digital trio that agrees on vendor, price, and quantity. The issue date is not printed, so extraction confidence sits on the 95% auto-clear line. Upload these three files together.",
            expected_routing="auto_clear",
            extraction_confidence=0.95,
        ),
        Bundle(
            "success-90-metro",
            [
                "27-po-24042-metro-polymers.jpg",
                "28-inv-10042-metro-polymers.jpg",
                "29-grn-31042-metro-polymers.jpg",
            ],
            "matched",
            [],
            "Straight photographs of a clean trio. The documents agree. A photograph is capped at 90%, under the 95% auto-clear line, so the case is reviewed. Upload these three files together.",
            expected_routing="flag",
            extraction_confidence=0.90,
        ),
    ]

    metro_common = dict(
        vendor_name=metro[0],
        vendor_address=metro[1],
        vendor_tax_id=metro[2],
        lines=metro_lines,
        subtotal=metro_sub,
        tax=metro_tax,
        total=metro_total,
    )
    photo_sources = [
        SampleDoc(
            "27-po-24042-metro-polymers.pdf",
            "purchase_order",
            "PO-24042",
            date(2026, 9, 8),
            **metro_common,
        ),
        SampleDoc(
            "28-inv-10042-metro-polymers.pdf",
            "invoice",
            "INV-10042",
            date(2026, 9, 15),
            po_number="PO-24042",
            **metro_common,
        ),
        SampleDoc(
            "29-grn-31042-metro-polymers.pdf",
            "goods_receipt",
            "GRN-31042",
            date(2026, 9, 15),
            po_number="PO-24042",
            received_by="A. Pawar",
            gate_entry="GE-4612",
            vehicle="MH12 GH 3090",
            **metro_common,
        ),
    ]
    return documents, bundles, scans, hindi_lines, hindi_sub, hindi_tax, hindi_total, photo_sources


def inr(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    whole, frac = f"{abs(quantized):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = [tail]
        while head:
            groups.append(head[-2:])
            head = head[:-2]
        whole = ",".join(reversed(groups))
    return f"{sign}Rs. {whole}.{frac}"


def pretty_date(value: date) -> str:
    return value.strftime("%d %b %Y")


class Page:
    def __init__(self, path: Path, hindi: bool) -> None:
        self.canvas = canvas.Canvas(str(path), pagesize=A4)
        self.hindi = hindi
        if hindi:
            if not HINDI_FONT.exists():
                raise SystemExit(f"Hindi font not found at {HINDI_FONT}")
            pdfmetrics.registerFont(TTFont("Body", str(HINDI_FONT)))
            self.font = "Body"
            self.font_bold = "Body"
        else:
            self.font = "Helvetica"
            self.font_bold = "Helvetica-Bold"

    def finish(self, title: str) -> None:
        self.canvas.setTitle(title)
        self.canvas.save()

    def text(self, x: float, y: float, value: str, size: float = 9, bold: bool = False, color=INK) -> None:
        self.canvas.setFillColor(color)
        self.canvas.setFont(self.font_bold if bold else self.font, size)
        self.canvas.drawString(x, y, value)

    def right(self, x: float, y: float, value: str, size: float = 9, bold: bool = False, color=INK) -> None:
        self.canvas.setFillColor(color)
        self.canvas.setFont(self.font_bold if bold else self.font, size)
        self.canvas.drawRightString(x, y, value)

    def wrapped(self, text: str, size: float, width: float, bold: bool = False) -> list[str]:
        font = self.font_bold if bold else self.font
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if self.canvas.stringWidth(trial, font, size) <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]


def render_stacked(spec: SampleDoc, path: Path) -> None:
    """One column, so a photograph still reads when OCR has no word boxes."""
    page = Page(path, False)
    title = _title(spec)
    y = PAGE_H - 48
    page.text(MARGIN, y, title, 14, bold=True, color=NAVY)
    y -= 28
    page.text(MARGIN, y, "SUPPLIER", 8, bold=True, color=TEAL)
    y -= 16
    for line in (spec.vendor_name, spec.vendor_address, f"GSTIN {spec.vendor_tax_id}"):
        page.text(MARGIN, y, line, 10)
        y -= 14
    y -= 12
    rows = [("Document no", spec.number)]
    if spec.show_date:
        rows.append(("Date", pretty_date(spec.issued)))
    if spec.po_number:
        rows.append(("PO number", spec.po_number))
    if spec.received_by:
        rows.append(("Received by", spec.received_by))
    for label, value in rows:
        page.text(MARGIN, y, label.upper(), 8, bold=True, color=MUTED)
        y -= 14
        page.text(MARGIN, y, value, 11, bold=True)
        y -= 18
    y -= 8
    for index, line in enumerate(spec.lines, start=1):
        text = (
            f"{index} {line.sku} {line.description} {line.quantity.normalize():f} {line.unit} "
            f"{inr(line.unit_price)} {inr(line.amount)}"
        )
        page.text(MARGIN, y, text, 9)
        y -= 16
    y -= 10
    for label, amount in (
        ("Subtotal", spec.subtotal),
        ("CGST 9%", spec.tax / 2),
        ("SGST 9%", spec.tax / 2),
        ("Total", spec.total),
    ):
        page.text(MARGIN, y, f"{label} {inr(amount)}", 10, bold=label == "Total")
        y -= 16
    page.finish(f"{title} {spec.number}")


def render_pdf(spec: SampleDoc, path: Path) -> None:
    page = Page(path, spec.language != "en")
    title = _title(spec)
    letterhead, letter_lines = _letterhead(spec)
    _draw_banner(page, letterhead, letter_lines, title)
    _draw_parties(page, spec)
    meta_bottom = _draw_meta(page, spec)
    bottom = _draw_lines(page, spec, meta_bottom - 18)
    _draw_totals(page, spec, bottom)
    _draw_footer(page, spec)
    page.finish(f"{title} {spec.number}")


def _title(spec: SampleDoc) -> str:
    if spec.language != "en" and spec.kind == "invoice":
        return "कर चालान  /  TAX INVOICE"
    return {"purchase_order": "PURCHASE ORDER", "invoice": "TAX INVOICE", "goods_receipt": "GOODS RECEIPT NOTE"}[
        spec.kind
    ]


def _letterhead(spec: SampleDoc) -> tuple[str, list[str]]:
    if spec.kind == "invoice":
        return spec.vendor_name, [spec.vendor_address, f"GSTIN {spec.vendor_tax_id}"]
    return BUYER["name"], [BUYER["address"], f"GSTIN {BUYER['tax_id']}"]


def _draw_banner(page: Page, name: str, lines: list[str], title: str) -> None:
    canvas_ = page.canvas
    canvas_.setFillColor(NAVY)
    canvas_.rect(0, PAGE_H - 86, PAGE_W, 86, fill=1, stroke=0)
    canvas_.setFillColor(AMBER)
    canvas_.rect(0, PAGE_H - 90, PAGE_W, 4, fill=1, stroke=0)
    page.text(MARGIN, PAGE_H - 36, name, 13, bold=True, color=white)
    y = PAGE_H - 52
    for line in lines:
        page.text(MARGIN, y, line, 8, color=HexColor("#D5E2EA"))
        y -= 12
    page.right(PAGE_W - MARGIN, PAGE_H - 40, title, 11, bold=True, color=white)


def _draw_parties(page: Page, spec: SampleDoc) -> None:
    if spec.kind == "purchase_order":
        left = ("Supplier", [spec.vendor_name, spec.vendor_address, f"GSTIN {spec.vendor_tax_id}"])
        right = ("Ship to", [BUYER["name"], BUYER["address"], f"GSTIN {BUYER['tax_id']}"])
    elif spec.kind == "invoice":
        left = ("Bill to", [BUYER["name"], BUYER["address"], f"GSTIN {BUYER['tax_id']}"])
        right = ("Supplier", [spec.vendor_name, spec.vendor_address, f"GSTIN {spec.vendor_tax_id}"])
    else:
        left = ("Supplier", [spec.vendor_name, spec.vendor_address, f"GSTIN {spec.vendor_tax_id}"])
        right = ("Received at", [BUYER["name"], "Stores, " + BUYER["address"], f"GSTIN {BUYER['tax_id']}"])
    _party_box(page, MARGIN, PAGE_H - 176, 250, left)
    _party_box(page, MARGIN + 270, PAGE_H - 176, 253, right)


def _party_box(page: Page, x: float, y: float, width: float, block: tuple[str, list[str]]) -> None:
    label, lines = block
    page.canvas.setStrokeColor(LINE)
    page.canvas.setFillColor(PAPER)
    page.canvas.roundRect(x, y, width, 72, 4, fill=1, stroke=1)
    page.text(x + 10, y + 56, label.upper(), 7, bold=True, color=TEAL)
    cursor = y + 40
    for line in lines:
        for wrapped in page.wrapped(line, 8.5, width - 20):
            page.text(x + 10, cursor, wrapped, 8.5)
            cursor -= 12


def _draw_meta(page: Page, spec: SampleDoc) -> float:
    rows = [("Document no", spec.number)]
    if spec.show_date:
        rows.append(("Date", pretty_date(spec.issued)))
    if spec.po_number:
        rows.append(("PO number", spec.po_number))
    if spec.kind == "goods_receipt" and spec.received_by:
        rows.append(("Received by", spec.received_by))
    if spec.gate_entry:
        rows.append(("Gate entry", spec.gate_entry))
    if spec.vehicle:
        rows.append(("Vehicle", spec.vehicle))
    y = PAGE_H - 198
    for index, (label, value) in enumerate(rows):
        column = index % 3
        if column == 0 and index:
            y -= 34
        x = MARGIN + column * 175
        page.text(x, y, label.upper(), 7, bold=True, color=MUTED)
        page.text(x, y - 12, value, 9, bold=True)
    return y - 16


def _draw_lines(page: Page, spec: SampleDoc, top: float) -> float:
    columns = [
        ("#", 22),
        ("SKU", 68),
        ("Description", 200),
        ("Qty", 46),
        ("Unit", 42),
        ("Rate", 68),
        ("Amount", 77),
    ]
    height = 22
    width = sum(size for _, size in columns)
    page.canvas.setFillColor(NAVY)
    page.canvas.rect(MARGIN, top - height, width, height, fill=1, stroke=0)
    x = MARGIN
    for label, size in columns:
        page.text(x + 4, top - 15, label, 8, bold=True, color=white)
        x += size
    y = top - height
    for index, line in enumerate(spec.lines, start=1):
        y -= height
        if index % 2 == 0:
            page.canvas.setFillColor(PAPER)
            page.canvas.rect(MARGIN, y, width, height, fill=1, stroke=0)
        values = [
            str(index),
            line.sku,
            line.description,
            f"{line.quantity.normalize():f}",
            line.unit,
            inr(line.unit_price),
            inr(line.amount),
        ]
        x = MARGIN
        for value, (_, size) in zip(values, columns, strict=True):
            page.text(x + 4, y + 7, value, 8)
            x += size
        page.canvas.setStrokeColor(LINE)
        page.canvas.line(MARGIN, y, MARGIN + width, y)
    return y


def _draw_totals(page: Page, spec: SampleDoc, table_bottom: float) -> None:
    rows = [("Subtotal", spec.subtotal), ("CGST 9%", spec.tax / 2), ("SGST 9%", spec.tax / 2), ("Total", spec.total)]
    if spec.tax == 0:
        rows = [("Value received", spec.total)]
    y = table_bottom - 28
    label_x = PAGE_W - MARGIN - 170
    amount_x = PAGE_W - MARGIN
    for label, amount in rows:
        bold = label == "Total"
        page.text(label_x, y, label, 9, bold=bold, color=INK if bold else MUTED)
        page.right(amount_x, y, inr(amount), 9, bold=bold)
        y -= 16
    if spec.remarks:
        page.text(MARGIN, table_bottom - 28, "Remarks", 7, bold=True, color=MUTED)
        cursor = table_bottom - 42
        for line in page.wrapped(spec.remarks, 8.5, 320):
            page.text(MARGIN, cursor, line, 8.5)
            cursor -= 12


def _draw_footer(page: Page, spec: SampleDoc) -> None:
    page.canvas.setStrokeColor(LINE)
    page.canvas.line(MARGIN, 72, PAGE_W - MARGIN, 72)
    note = spec.footer_note or "Original for recipient"
    page.text(MARGIN, 56, note, 8, color=MUTED)
    page.text(MARGIN, 42, "Payment terms: 30 days from goods receipt.", 8, color=MUTED)
    page.right(PAGE_W - MARGIN, 84, "Authorised signatory", 8, color=MUTED)
    page.canvas.setStrokeColor(INK)
    page.canvas.line(PAGE_W - MARGIN - 130, 96, PAGE_W - MARGIN, 96)


def render_scan(pdf_path: Path, dest: Path, angle: float, shear: float, quality: int, *, faithful: bool = False) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    bitmap = pdf[0].render(scale=2)
    image = bitmap.to_pil().convert("RGB")
    pdf.close()

    paper = Image.new("RGB", image.size, (246, 241, 232))
    image = Image.blend(paper, image, 0.94)
    if faithful:
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format="JPEG", quality=quality, optimize=True)
        return
    padded = Image.new("RGB", (image.width + 140, image.height + 140), (176, 168, 156))
    padded.paste(image, (70, 70))
    image = _shear(padded, shear)
    image = image.rotate(angle, expand=True, fillcolor=(176, 168, 156), resample=Image.Resampling.BICUBIC)
    image = ImageEnhance.Contrast(image).enhance(0.9)
    image = ImageEnhance.Color(image).enhance(0.25)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.55))
    noise = Image.effect_noise(image.size, 7).convert("RGB")
    image = Image.blend(image, noise, 0.07)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.convert("L").convert("RGB").save(dest, format="JPEG", quality=quality, optimize=True)


def _shear(image: Image.Image, factor: float) -> Image.Image:
    width, height = image.size
    extra = abs(int(factor * height)) + 8
    offset = extra if factor > 0 else 4
    return image.transform(
        (width + extra, height),
        Image.Transform.AFFINE,
        (1, -factor, offset, 0, 1, 0),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(176, 168, 156),
    )


def to_model(spec: SampleDoc) -> PurchaseOrder | Invoice | GoodsReceipt:
    payload = {
        "document_number": spec.number,
        "document_date": spec.issued if spec.show_date else None,
        "currency": "INR",
        "vendor": Party(name=spec.vendor_name, tax_id=spec.vendor_tax_id, address=spec.vendor_address),
        "line_items": [
            LineItem(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for line in spec.lines
        ],
        "subtotal": spec.subtotal,
        "tax": spec.tax,
        "total": spec.total,
    }
    if spec.kind == "purchase_order":
        return PurchaseOrder(**payload)
    if spec.kind == "invoice":
        return Invoice(**payload, po_number=spec.po_number or "")
    return GoodsReceipt(**payload, po_number=spec.po_number or "", received_by=spec.received_by)


def record(spec: SampleDoc) -> dict:
    return {
        "file": spec.filename,
        "presentation": spec.presentation,
        "language": spec.language,
        "text_layer": spec.text_layer,
        "planted_error": spec.planted_error,
        "alternate_of": spec.alternate_of,
        "expected_validation": spec.expected_validation,
        "document": to_model(spec).model_dump(mode="json"),
    }


def check_bundles(records: list[dict], bundles: list[Bundle]) -> None:
    by_file = {item["file"]: item for item in records}
    for bundle in bundles:
        extractions = []
        for filename in bundle.files:
            document = by_file[filename]["document"]
            model = {
                "purchase_order": PurchaseOrder,
                "invoice": Invoice,
                "goods_receipt": GoodsReceipt,
            }[document["document_type"]]
            parsed = model.model_validate(document)
            extractions.append(
                Extraction(
                    file_id=filename,
                    document_type=parsed.document_type,
                    confidence=0.95,
                    document=parsed,
                )
            )
            issues = [issue.code for issue in issues_for_extraction(extractions[-1])]
            expected = by_file[filename]["expected_validation"]
            if issues != expected:
                raise SystemExit(f"{filename} validation {issues} != {expected}")
        matched = three_way_match(extractions)
        if matched.status != bundle.expected_status or matched.exceptions != bundle.expected_exceptions:
            raise SystemExit(
                f"{bundle.id}: got {matched.status} {matched.exceptions}, "
                f"expected {bundle.expected_status} {bundle.expected_exceptions}"
            )
        if bundle.expected_routing is None:
            continue
        scored = [
            item.model_copy(update={"confidence": bundle.extraction_confidence, "completeness": 1.0})
            for item in extractions
        ]
        routed = assess(scored, matched, [], auto_clear=0.95, flag=0.70)
        if routed.routing != bundle.expected_routing or routed.scores.routing_score != bundle.extraction_confidence:
            raise SystemExit(
                f"{bundle.id}: routing {routed.routing} score {routed.scores.routing_score}, "
                f"expected {bundle.expected_routing} at {bundle.extraction_confidence}"
            )


def write_readme(records: list[dict], bundles: list[Bundle]) -> None:
    lines = [
        "# Sample documents",
        "",
        f"{len(records)} synthetic accounts-payable documents for Northwind Fabrication Pvt Ltd, Pune.",
        "Amounts are INR. GST is split into CGST and SGST on the page and stored as one `tax` field.",
        "",
        "Digital PDFs have a text layer. A complete text layer scores 100%. A text layer with no issue date scores 95%, which is the auto-clear line. A photograph is capped at 90%, so a clean photo match is reviewed.",
        "",
        "The skewed `.jpg` files need OCR or a vision model. `20-inv-5520-gupta-hindi.jpg` is mixed Hindi and English. `27` through `29` are straight photographs of a clean trio.",
        "",
        "Upload each success trio on its own. Matching the whole pack in one case mixes the planted errors into the clean sets.",
        "",
        "## Cases",
        "",
    ]
    for bundle in bundles:
        files = ", ".join(f"`{name}`" for name in bundle.files)
        exceptions = ", ".join(bundle.expected_exceptions) if bundle.expected_exceptions else "none"
        lines.append(f"- **{bundle.id}** ({bundle.expected_status}: {exceptions}). {bundle.summary} Files: {files}.")
    lines.extend(
        [
            "",
            "Three photographs are skewed copies of the Bharat invoice, the Bharat goods receipt, and the Lakshmi purchase order. Their labels point at those PDFs. The fourth photograph is the Hindi invoice. Three more are straight photographs of the Metro Polymers trio, kept so a clean photo can be tested at the 90% cap.",
            "",
            "Regenerate with:",
            "",
            "```bash",
            "cd backend",
            "uv run python scripts/generate_sample_data.py",
            "```",
            "",
        ]
    )
    del records
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    documents, bundles, scans, hindi_lines, hindi_sub, hindi_tax, hindi_total, photo_sources = catalog()
    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in DOCUMENT_DIR.iterdir():
        stale.unlink()

    by_name = {spec.filename: spec for spec in documents}
    for spec in documents:
        render_pdf(spec, DOCUMENT_DIR / spec.filename)

    scan_records: list[SampleDoc] = []
    for filename, source_name, angle, shear, quality in scans:
        render_scan(DOCUMENT_DIR / source_name, DOCUMENT_DIR / filename, angle, shear, quality)
        source = by_name[source_name]
        scan_records.append(
            SampleDoc(
                filename,
                source.kind,
                source.number,
                source.issued,
                source.vendor_name,
                source.vendor_address,
                source.vendor_tax_id,
                source.lines,
                source.subtotal,
                source.tax,
                source.total,
                po_number=source.po_number,
                received_by=source.received_by,
                language="en",
                presentation="scan",
                planted_error=source.planted_error,
                alternate_of=source_name,
                expected_validation=list(source.expected_validation),
                text_layer=False,
            )
        )

    photo_records: list[SampleDoc] = []
    with tempfile.TemporaryDirectory() as temporary:
        temp_dir = Path(temporary)
        for source in photo_sources:
            pdf_path = temp_dir / source.filename
            render_stacked(source, pdf_path)
            photo_name = source.filename.replace(".pdf", ".jpg")
            render_scan(pdf_path, DOCUMENT_DIR / photo_name, 0, 0, 95, faithful=True)
            photo_records.append(
                SampleDoc(
                    photo_name,
                    source.kind,
                    source.number,
                    source.issued,
                    source.vendor_name,
                    source.vendor_address,
                    source.vendor_tax_id,
                    source.lines,
                    source.subtotal,
                    source.tax,
                    source.total,
                    po_number=source.po_number,
                    received_by=source.received_by,
                    language="en",
                    presentation="scan",
                    text_layer=False,
                )
            )

    hindi = SampleDoc(
        "20-inv-5520-gupta-hindi.jpg",
        "invoice",
        "INV-5520",
        date(2026, 9, 18),
        "गुप्ता इंडस्ट्रियल सप्लाई",
        "दुकान 12, बाजार रोड, पिंपरी, पुणे 411018",
        "27AABCG6677E1Z9",
        hindi_lines,
        hindi_sub,
        hindi_tax,
        hindi_total,
        po_number="PO-24030",
        language="hi-en",
        presentation="scan",
        planted_error=None,
        text_layer=False,
        footer_note="मूल प्रति  /  Original for recipient",
    )
    with tempfile.TemporaryDirectory() as temporary:
        hindi_pdf = Path(temporary) / "gupta.pdf"
        render_pdf(hindi, hindi_pdf)
        render_scan(hindi_pdf, DOCUMENT_DIR / hindi.filename, -2.2, 0.04, 64)

    records = [record(spec) for spec in documents]
    records.extend(record(spec) for spec in scan_records)
    records.append(record(hindi))
    records.extend(record(spec) for spec in photo_records)
    if len(records) != 29:
        raise SystemExit(f"Expected 29 documents, got {len(records)}")

    check_bundles(records, bundles)
    payload = {
        "buyer": BUYER,
        "currency": "INR",
        "documents": records,
        "bundles": [
            {
                "id": bundle.id,
                "files": bundle.files,
                "expected_status": bundle.expected_status,
                "expected_exceptions": bundle.expected_exceptions,
                "summary": bundle.summary,
                **(
                    {
                        "expected_routing": bundle.expected_routing,
                        "extraction_confidence": bundle.extraction_confidence,
                    }
                    if bundle.expected_routing is not None
                    else {}
                ),
            }
            for bundle in bundles
        ],
    }
    (OUTPUT_DIR / "ground_truth.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_readme(records, bundles)
    print(f"Wrote {len(records)} documents to {DOCUMENT_DIR}")


if __name__ == "__main__":
    main()
