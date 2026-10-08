"""The layout parser runs first. The model is called only when a required field is missing."""

import json

import redis

from app.core.config import get_settings
from app.pipeline.extract import extract_read
from app.pipeline.ollama import Completion, OllamaError
from app.pipeline.read_text import ReadText
from app.services.cache import MemoryCache, RedisCache

INVOICE = {
    "document_type": "invoice",
    "document_number": "INV-1",
    "document_date": "2024-01-12",
    "currency": "INR",
    "po_number": "PO-1",
    "vendor": {"name": "Acme Steels", "tax_id": None, "address": None},
    "line_items": [
        {
            "sku": "PLT",
            "description": "Steel plate",
            "quantity": "2",
            "unit": "kg",
            "unit_price": "10.00",
            "amount": "20.00",
        }
    ],
    "subtotal": "20.00",
    "tax": "3.60",
    "total": "23.60",
}

PURCHASE_ORDER = """\
SUPPLIER
Acme Steels
Mumbai
GSTIN 27AAPFU0939F1ZV
PURCHASE ORDER
DOCUMENT NO: PO-100
DATE: 12 Jan 2024
1 PLT Steel plate 2 kg Rs. 10.00 Rs. 20.00
SUBTOTAL Rs. 20.00
CGST Rs. 1.80
SGST Rs. 1.80
TOTAL Rs. 23.60
"""


def test_a_complete_layout_does_not_call_the_model():
    def chat(_prompt):
        raise AssertionError("the model should not be called")

    extraction = extract_read(
        "file-1",
        "po.pdf",
        ReadText(text=PURCHASE_ORDER, source="pdf"),
        completer=chat,
    )
    assert extraction.document is not None
    assert extraction.document.document_number == "PO-100"
    assert extraction.document.vendor.name == "Acme Steels"
    assert extraction.extractor == "pdf"
    assert extraction.input_tokens == 0


def test_extract_caches_the_model_answer_and_reuses_it():
    cache = MemoryCache()
    calls = {"chat": 0}
    prompts: list[str] = []

    def chat(prompt):
        calls["chat"] += 1
        prompts.append(prompt)
        return Completion(json.dumps(INVOICE), 11, 7)

    read = ReadText(text="Steel plate invoice for Acme Steels", source="pdf")
    first = extract_read("file-1", "a.pdf", read, cache=cache, completer=chat)
    assert first.document is not None
    assert first.document.document_number == "INV-1"
    assert first.document.vendor.name == "Acme Steels"
    assert first.extractor == f"ollama:{get_settings().ollama_model}"
    assert first.input_tokens == 11
    assert first.output_tokens == 7
    assert "Steel plate invoice for Acme Steels" in prompts[0]
    assert "Page:" in prompts[0]
    assert calls["chat"] == 1

    second = extract_read("file-2", "b.pdf", read, cache=cache, completer=chat)
    assert second.file_id == "file-2"
    assert second.source_name == "b.pdf"
    assert second.document is not None
    assert second.document.document_number == "INV-1"
    assert calls["chat"] == 1


def test_ollama_errors_stay_on_the_extraction():
    cache = MemoryCache()

    def chat(_prompt):
        raise OllamaError("Ollama is not reachable at http://127.0.0.1:11434.")

    extraction = extract_read(
        "file-1",
        "a.txt",
        ReadText(text="hello invoice", source="text"),
        cache=cache,
        completer=chat,
    )
    assert extraction.document is None
    assert extraction.confidence == 0
    assert "not reachable" in extraction.warnings[-1]
    assert cache._values == {}


def test_a_dead_cache_still_returns_the_model_document():
    class Down:
        available = False

        def get_json(self, _key):
            return None

        def set_json(self, _key, _value, _ttl):
            raise AssertionError("a dead cache should not be written")

    def chat(_prompt):
        return Completion(json.dumps(INVOICE), 1, 1)

    extraction = extract_read(
        "file-1",
        "a.pdf",
        ReadText(text="Steel plate invoice", source="pdf"),
        cache=Down(),
        completer=chat,
    )
    assert extraction.document is not None
    assert any("Redis" in warning for warning in extraction.warnings)


def test_a_two_page_receipt_keeps_every_line_and_the_last_total():
    def chat(_prompt):
        raise AssertionError("the model should not be called")

    first = """\
SUPPLIER
Acme Steels
Mumbai
GSTIN 27AAPFU0939F1ZV
PURCHASE ORDER
DOCUMENT NO: PO-100
DATE: 12 Jan 2024
1 PLT Steel plate 2 kg Rs. 10.00 Rs. 20.00
"""
    second = """\
2 ROD Steel rod 1 kg Rs. 5.00 Rs. 5.00
SUBTOTAL Rs. 25.00
CGST Rs. 2.25
SGST Rs. 2.25
TOTAL Rs. 29.50
"""
    extraction = extract_read(
        "file-1",
        "po.pdf",
        ReadText(text=first + second, source="pdf", pages=[first, second]),
        completer=chat,
    )
    assert extraction.document is not None
    assert extraction.document.document_number == "PO-100"
    assert [line.sku for line in extraction.document.line_items] == ["PLT", "ROD"]
    assert str(extraction.document.total) == "29.50"
    assert extraction.extractor == "pdf"


def test_a_long_receipt_is_sent_in_page_groups(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("AP_MODEL_MAX_CHARS", "80")
    get_settings.cache_clear()
    prompts: list[str] = []

    def chat(prompt):
        prompts.append(prompt)
        return Completion(json.dumps(INVOICE), 1, 1)

    pages = [f"page {index} " + ("x" * 50) for index in range(3)]
    try:
        extraction = extract_read(
            "file-1",
            "long.pdf",
            ReadText(text="\n".join(pages), source="pdf", pages=pages),
            cache=MemoryCache(),
            completer=chat,
        )
    finally:
        get_settings.cache_clear()
    assert len(prompts) == 3
    assert all(page in prompts[index] and pages[(index + 1) % 3] not in prompts[index] for index, page in enumerate(pages))
    assert extraction.document is not None
    assert len(extraction.document.line_items) == 3


def test_redis_cache_roundtrip_and_outage():
    class Store:
        def __init__(self):
            self.values: dict[str, str] = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, ex=None):
            self.values[key] = value

    cache = RedisCache("redis://example", client=Store())
    cache.set_json("ap:extract", {"ok": True}, 30)
    assert cache.get_json("ap:extract") == {"ok": True}
    assert cache.available is True

    class Dead:
        def get(self, _key):
            raise redis.ConnectionError("down")

        def set(self, _key, _value, ex=None):
            raise redis.ConnectionError("down")

    down = RedisCache("redis://example", client=Dead())
    assert down.get_json("ap:extract") is None
    assert down.available is False
    down.set_json("ap:extract", {"ok": False}, 10)
