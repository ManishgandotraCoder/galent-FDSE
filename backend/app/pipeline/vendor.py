"""Resolve a vendor from the GSTIN, then the legal name, then a fuzzy name.

There is no ERP vendor master in this prototype. The GSTIN printed on the
document is the identity. A legal-form difference ("Pvt Ltd" and "Private
Limited") with the same GSTIN is a normalization, not a different vendor.
A fuzzy name without a matching GSTIN is only a hint and does not clear.
"""

from difflib import SequenceMatcher

from app.schemas.documents import Party

_SUFFIXES = frozenset(
    {
        "private",
        "limited",
        "pvt",
        "ltd",
        "llp",
        "inc",
        "incorporated",
        "co",
        "company",
    }
)

FUZZY_REVIEW = 0.92


class VendorDecision:
    def __init__(self, agreed: bool, method: str, left_norm: str, right_norm: str) -> None:
        self.agreed = agreed
        self.method = method
        self.left_norm = left_norm
        self.right_norm = right_norm


def gstin_key(tax_id: str | None) -> str | None:
    if not tax_id:
        return None
    key = "".join(char for char in tax_id.upper() if char.isalnum())
    return key or None


def normalize_name(name: str) -> str:
    folded = name.casefold().replace("&", " and ")
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in folded)
    tokens = cleaned.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def raw_name(name: str) -> str:
    return "".join(char for char in name.casefold() if char.isalnum())


def vendors_agree(left: Party, right: Party) -> VendorDecision:
    left_gst = gstin_key(left.tax_id)
    right_gst = gstin_key(right.tax_id)
    left_norm = normalize_name(left.name)
    right_norm = normalize_name(right.name)
    if left_gst and right_gst:
        if left_gst == right_gst:
            return VendorDecision(True, "gstin", left_norm, right_norm)
        return VendorDecision(False, "gstin_conflict", left_norm, right_norm)
    if left_norm and left_norm == right_norm:
        return VendorDecision(True, "normalized_name", left_norm, right_norm)
    if left_norm and right_norm and fuzzy_name(left_norm, right_norm) >= FUZZY_REVIEW:
        return VendorDecision(False, "fuzzy", left_norm, right_norm)
    return VendorDecision(False, "mismatch", left_norm, right_norm)


def fuzzy_name(left: str, right: str) -> float:
    left_sorted = " ".join(sorted(left.split()))
    right_sorted = " ".join(sorted(right.split()))
    return SequenceMatcher(None, left_sorted, right_sorted).ratio()


def identity(file_id: str, vendor: Party) -> dict:
    return {
        "file_id": file_id,
        "vendor_name": vendor.name,
        "normalized_name": normalize_name(vendor.name),
        "tax_id": gstin_key(vendor.tax_id),
    }
