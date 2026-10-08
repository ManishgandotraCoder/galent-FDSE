from decimal import Decimal

from app.schemas.documents import Extraction, GoodsReceipt, Invoice, LineItem, Party, PurchaseOrder


def party(name: str = "Acme Metals Pvt. Ltd.") -> Party:
    return Party(name=name)


def line(
    quantity: str = "10",
    unit_price: str = "100",
    amount: str | None = "1000",
    sku: str = "SP-1",
) -> LineItem:
    return LineItem(
        description="Steel plate",
        sku=sku,
        quantity=Decimal(quantity),
        unit="kg",
        unit_price=Decimal(unit_price),
        amount=None if amount is None else Decimal(amount),
    )


def purchase_order(
    vendor: str = "Acme Metals Pvt. Ltd.",
    quantity: str = "10",
    total: str | None = "1000",
    unit_price: str = "100",
) -> PurchaseOrder:
    amount = None if total is None else str(Decimal(quantity) * Decimal(unit_price))
    return PurchaseOrder(
        document_number="PO-1001",
        currency="INR",
        vendor=party(vendor),
        line_items=[line(quantity=quantity, unit_price=unit_price, amount=amount)],
        total=None if total is None else Decimal(total),
    )


def invoice(
    vendor: str = "acme metals pvt ltd",
    quantity: str = "10",
    total: str | None = "1000",
    unit_price: str = "100",
    number: str = "INV-55",
    po_number: str = "PO-1001",
) -> Invoice:
    amount = None if total is None else str(Decimal(quantity) * Decimal(unit_price))
    return Invoice(
        document_number=number,
        po_number=po_number,
        currency="inr",
        vendor=party(vendor),
        line_items=[line(quantity=quantity, unit_price=unit_price, amount=amount)],
        total=None if total is None else Decimal(total),
    )


def goods_receipt(
    vendor: str = "Acme Metals Pvt. Ltd.",
    quantity: str = "10",
    total: str | None = None,
    unit_price: str = "100",
) -> GoodsReceipt:
    return GoodsReceipt(
        document_number="GRN-9",
        po_number="PO-1001",
        vendor=party(vendor),
        line_items=[line(quantity=quantity, unit_price=unit_price, amount=None if total is None else total)],
        total=None if total is None else Decimal(total),
    )


def extraction(document, confidence: float = 0.95, file_id: str = "file") -> Extraction:
    return Extraction(
        file_id=file_id,
        document_type=document.document_type,
        confidence=confidence,
        document=document,
    )
