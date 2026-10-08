from datetime import date

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.pipeline.graph import build_graph
from app.pipeline.match import assess, build_email, three_way_match
from tests.helpers import extraction, goods_receipt, invoice, purchase_order


def test_clean_extraction_auto_clears_without_approval():
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "clear-1"}}
    documents = [
        extraction(purchase_order(), file_id="po"),
        extraction(invoice(), file_id="inv"),
        extraction(goods_receipt(), file_id="grn"),
    ]
    graph.invoke(
        {
            "file_ids": ["po", "inv", "grn"],
            "extractions": [item.model_dump(mode="json") for item in documents],
            "status": "started",
        },
        config,
    )
    snapshot = graph.get_state(config)
    assert snapshot.next == ()
    assert snapshot.values["status"] == "cleared"
    assert snapshot.values["routing"] == "auto_clear"
    assert snapshot.values["email_draft"] is None


def test_unreadable_file_pauses_until_a_person_decides():
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "hold-1"}}
    graph.invoke({"file_ids": ["missing"], "status": "started"}, config)
    waiting = graph.get_state(config)

    assert waiting.next == ("approval",)
    assert waiting.values["status"] == "awaiting_approval"
    assert waiting.values["routing"] == "reject"
    assert waiting.values["email_draft"]["to_role"] == "approver"
    assert waiting.values["email_draft"]["requires_approval"] is True

    graph.invoke(Command(resume={"approved": False, "note": "Do not send."}), config)
    done = graph.get_state(config)
    assert done.next == ()
    assert done.values["status"] == "declined"
    assert done.values["approval"] == {"approved": False, "note": "Do not send."}


def test_commercial_exception_drafts_a_vendor_email():
    matched_codes = ["partial_delivery"]
    email = build_email(
        routing="flag",
        primary="partial_delivery",
        codes=matched_codes,
        match=None,
        confidence=0.95,
    )
    assert email.to_role == "vendor"
    assert email.requires_approval is True
    assert "has not been sent" in email.body


def test_vendor_email_tells_the_document_history():
    documents = [
        extraction(purchase_order().model_copy(update={"document_date": date(2026, 9, 4)}), file_id="po"),
        extraction(invoice().model_copy(update={"document_date": date(2026, 9, 16)}), file_id="inv"),
        extraction(
            goods_receipt(quantity="6").model_copy(update={"document_date": date(2026, 9, 15), "received_by": "S. Patil"}),
            file_id="grn",
        ),
    ]
    matched = three_way_match(documents)
    result = assess(documents, matched, [], auto_clear=0.95, flag=0.70)
    email = build_email(
        routing=result.routing,
        primary=result.primary_exception,
        codes=list(result.exception_codes),
        match=matched,
        confidence=result.confidence,
        extractions=documents,
        scores=result.scores,
        exceptions=result.exceptions,
    )
    assert email.to_role == "vendor"
    assert "04 Sep 2026" in email.body
    assert "15 Sep 2026" in email.body
    assert "Received by S. Patil" in email.body
    assert "What we have on file" in email.body
    assert "What does not agree" in email.body
    assert "What we need from you" in email.body
    assert "has not been sent" in email.body
