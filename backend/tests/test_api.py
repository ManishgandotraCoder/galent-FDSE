from app.core.config import get_settings
from app.pipeline.graph import reset_graph
from app.services.storage import save_uploads


def test_upload_runs_in_the_background_and_reports_progress(client):
    idle = client.get("/api/intake")
    assert idle.status_code == 200
    assert idle.json()["status"] == "idle"
    assert idle.json()["uploaded"] == 0

    created = client.post(
        "/api/files",
        files=[
            ("files", ("po.txt", b"Purchase order PO-1", "text/plain")),
            ("files", ("invoice.txt", b"Invoice INV-1", "text/plain")),
        ],
    )
    assert created.status_code == 200
    body = _wait_for_intake(client)
    assert body["status"] == "done"
    assert body["uploaded"] == 2
    assert body["processed"] == 2
    assert body["total"] == 2
    assert body["message"] == "2 documents uploaded"
    assert body["run_id"]
    runs = client.get("/api/runs").json()["runs"]
    assert [run["id"] for run in runs] == [body["run_id"]]
    report = client.get("/api/eval")
    assert report.status_code == 200
    evaluation = report.json()
    assert evaluation["documents_processed"] == 2
    assert evaluation["field_accuracy"] is None
    assert {row["document_id"] for row in evaluation["documents"]} == {"po.txt", "invoice.txt"}
    assert evaluation["bundles"] == []


def test_clear_removes_files_cases_and_progress(client):
    uploaded = client.post("/api/files", files=[("files", ("note.txt", b"hello", "text/plain"))])
    assert uploaded.status_code == 200
    _wait_for_intake(client)

    cleared = client.post("/api/clear")
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert client.get("/api/files").json()["files"] == []
    assert client.get("/api/runs").json()["runs"] == []
    intake = client.get("/api/intake").json()
    assert intake["status"] == "idle"
    assert intake["uploaded"] == 0
    assert intake["message"] == ""


def _wait_for_intake(client):
    import time

    last = {}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        last = client.get("/api/intake").json()
        if last["status"] in {"done", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(last)


def test_eval_clear_deletes_database_cases(client):
    uploaded = client.post("/api/files", files=[("files", ("note.txt", b"hello", "text/plain"))])
    assert uploaded.status_code == 200
    _wait_for_intake(client)
    data = get_settings().data_dir
    assert (data / "checkpoints.sqlite").is_file()
    assert client.get("/api/runs").json()["runs"]

    cleared = client.delete("/api/eval")
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert client.get("/api/runs").json()["runs"] == []
    assert not (data / "checkpoints.sqlite").exists()
    assert not (data / "eval_report.json").exists()
    assert client.get("/api/eval").status_code == 404
    assert client.get("/api/files").json()["files"]


def test_post_eval_runs_the_labelled_pack(client, monkeypatch):
    report = {"documents_processed": 4, "documents": [], "bundles": []}

    def fake_run():
        return report

    monkeypatch.setattr("app.api.eval.run_evaluation", fake_run)
    created = client.post("/api/eval")
    assert created.status_code == 200
    assert created.json()["documents_processed"] == 4
    assert client.get("/api/eval").json()["documents_processed"] == 4


def test_sample_document_is_served_inline(client):
    found = client.get("/api/eval/documents/01-po-24018-apex-steel.pdf")
    assert found.status_code == 200
    assert found.headers["content-type"].startswith("application/pdf")
    assert found.content.startswith(b"%PDF")
    assert "inline" in found.headers["content-disposition"]
    missing = client.get("/api/eval/documents/not-a-file.pdf")
    assert missing.status_code == 404
    escaped = client.get("/api/eval/documents/..%2Fconfig.py")
    assert escaped.status_code == 404


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_list_download_and_delete(client):
    created = client.post("/api/files", files=[("files", ("note.txt", b"hello", "text/plain"))])
    assert created.status_code == 200
    body = created.json()
    assert body["limit"] == 20
    assert body["files"][0]["name"] == "note.txt"
    assert body["files"][0]["uploadedAt"]
    file_id = body["added"][0]["id"]

    downloaded = client.get(f"/api/files/{file_id}")
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello"
    assert downloaded.headers["content-type"].startswith("text/plain")

    attachment = client.get(f"/api/files/{file_id}?download=1")
    assert "attachment" in attachment.headers["content-disposition"]

    removed = client.delete(f"/api/files/{file_id}")
    assert removed.status_code == 200
    assert removed.json()["files"] == []
    assert client.get(f"/api/files/{file_id}").status_code == 404


def test_rejects_unsupported_and_extra_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AP_MAX_FILES", "1")
    get_settings.cache_clear()
    reset_graph()

    first = save_uploads([("program.exe", b"nope"), ("note.txt", b"hello")])
    assert [item.name for item in first.added] == ["note.txt"]
    assert first.rejected[0].reason == "This file type is not supported."

    second = save_uploads([("other.txt", b"world")])
    assert second.added == []
    assert second.rejected[0].reason == "You can upload 1 file at most."


def test_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AP_MAX_FILE_BYTES", "4")
    get_settings.cache_clear()

    result = save_uploads([("big.txt", b"123456"), ("empty.txt", b"")])
    assert result.added == []
    assert result.rejected[0].reason == "This file is larger than 4 bytes."
    assert result.rejected[1].reason == "This file is empty."


def test_run_requires_a_real_file_then_waits_for_approval(client):
    missing = client.post("/api/runs", json={"file_ids": ["not-real"]})
    assert missing.status_code == 400

    uploaded = client.post("/api/files", files=[("files", ("invoice.txt", b"unstructured", "text/plain"))])
    file_id = uploaded.json()["added"][0]["id"]
    created = client.post("/api/runs", json={"file_ids": [file_id]})
    assert created.status_code == 200
    run = created.json()
    assert run["awaiting_approval"] is True
    assert run["routing"] == "reject"
    assert run["email_draft"]["to_role"] == "approver"
    assert "Nothing has been sent" in run["email_draft"]["body"]

    approved = client.post(f"/api/runs/{run['id']}/approval", json={"approved": True, "note": "Reviewed."})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["awaiting_approval"] is False
    assert approved.json()["approval"]["approved"] is True

    again = client.post(f"/api/runs/{run['id']}/approval", json={"approved": True})
    assert again.status_code == 409
    assert client.get("/api/runs/not-a-run").status_code == 404
