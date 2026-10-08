from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal["purchase_order", "invoice", "goods_receipt"]


class Party(BaseModel):
    name: str = Field(min_length=1)
    tax_id: str | None = None
    address: str | None = None


class LineItem(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    unit: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    sku: str | None = None


class DocumentFields(BaseModel):
    document_number: str = Field(min_length=1)
    document_date: date | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    vendor: Party
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class PurchaseOrder(DocumentFields):
    document_type: Literal["purchase_order"] = "purchase_order"


class Invoice(DocumentFields):
    document_type: Literal["invoice"] = "invoice"
    po_number: str = Field(min_length=1)


class GoodsReceipt(DocumentFields):
    document_type: Literal["goods_receipt"] = "goods_receipt"
    po_number: str = Field(min_length=1)
    received_by: str | None = None


Document = Annotated[
    PurchaseOrder | Invoice | GoodsReceipt,
    Field(discriminator="document_type"),
]


class Extraction(BaseModel):
    """One stored file after extraction.

    `completeness` is the share of required fields the reader found.
    `confidence` is how much to trust the characters: text-layer, OCR, or the
    local model. Neither number is a decision to pay the invoice.
    """

    model_config = ConfigDict(use_enum_values=True)

    file_id: str
    source_name: str | None = None
    document_type: DocumentType | None = None
    completeness: float = Field(default=1, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    document: Document | None = None
    warnings: list[str] = Field(default_factory=list)
    extractor: str | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    input_tokens: int = 0
    output_tokens: int = 0
