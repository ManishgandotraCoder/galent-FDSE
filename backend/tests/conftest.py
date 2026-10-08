import pytest
from fastapi.testclient import TestClient

from app.services.cache import reset_cache
from app.core.config import get_settings
from app.services.intake import drain_intake
from app.pipeline.graph import reset_graph
from app.pipeline.parse import parse_read


def _layout_extract(file_id, source_name, read, **_kwargs):
    return parse_read(file_id, source_name, read)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_cache()
    reset_graph()
    monkeypatch.setattr("app.pipeline.extract.extract_read", _layout_extract)
    monkeypatch.setattr("app.pipeline.graph.extract_read", _layout_extract)
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    drain_intake()
    reset_graph()
    reset_cache()
    get_settings.cache_clear()
