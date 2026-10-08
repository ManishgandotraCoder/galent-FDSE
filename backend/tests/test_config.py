import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging


def _fresh():
    get_settings.cache_clear()


def test_log_level_is_normalized(monkeypatch):
    monkeypatch.setenv("AP_LOG_LEVEL", "debug")
    _fresh()
    try:
        assert get_settings().log_level == "DEBUG"
    finally:
        _fresh()


def test_environment_accepts_short_name(monkeypatch):
    monkeypatch.setenv("AP_ENV", "production")
    _fresh()
    try:
        assert get_settings().environment == "production"
    finally:
        _fresh()


def test_unknown_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("AP_LOG_LEVEL", "loud")
    _fresh()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        _fresh()


def test_flag_threshold_cannot_sit_above_auto_clear(monkeypatch):
    monkeypatch.setenv("AP_FLAG_CONFIDENCE", "0.99")
    monkeypatch.setenv("AP_AUTO_CLEAR_CONFIDENCE", "0.50")
    _fresh()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        _fresh()


def test_text_log_line_includes_the_message(capsys):
    setup_logging("INFO", "text")
    get_logger("app.tests.config").info("hello from test")
    assert "hello from test" in capsys.readouterr().out


def test_json_log_line_is_one_object(capsys):
    setup_logging("INFO", "json")
    get_logger("app.tests.config").warning("cache skipped")
    line = capsys.readouterr().out.strip()
    assert line.startswith("{")
    assert '"message": "cache skipped"' in line
