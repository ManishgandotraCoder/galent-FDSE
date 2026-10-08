"""One logger for the whole API.

Call `setup_logging()` once, when the process starts. In any other file:

    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("case finished run_id=%s routing=%s", run_id, routing)

`AP_LOG_LEVEL` is DEBUG, INFO, WARNING, ERROR, or CRITICAL.
`AP_LOG_FORMAT=text` is the easiest to read. `json` is one object per line.
"""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str, log_format: str) -> None:
    """Attach one handler to the `app` logger. Safe to call more than once."""
    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()
    app_logger.setLevel(level.upper())
    app_logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    app_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Logger for this module. Pass `__name__`."""
    if name == "app" or name.startswith("app."):
        return logging.getLogger(name)
    return logging.getLogger(f"app.{name}")
