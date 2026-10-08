"""Clean fields the matcher will compare.

Names keep their legal wording. "Pvt Ltd" and "Private Limited" stay different
on purpose: whether that is the same vendor is a question for the AP head.
Currency is uppercased and extra whitespace is removed. Totals are not rewritten.
"""

from app.schemas.documents import Extraction


def normalize_extraction(extraction: Extraction) -> Extraction:
    document = extraction.document
    if document is None:
        return extraction
    vendor = document.vendor.model_copy(update={"name": " ".join(document.vendor.name.split())})
    lines = [
        line.model_copy(update={"description": " ".join(line.description.split())})
        for line in document.line_items
    ]
    document = document.model_copy(update={"vendor": vendor, "line_items": lines, "currency": document.currency.upper()})
    return extraction.model_copy(
        update={"document": document, "document_type": document.document_type}
    )
