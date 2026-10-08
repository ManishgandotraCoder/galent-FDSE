"""Local Ollama call that fills one page into JSON."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CHAT_TIMEOUT = 180
_slots: threading.BoundedSemaphore | None = None
_slots_lock = threading.Lock()

SYSTEM = (
    "You extract one accounts-payable document into JSON. "
    "Use only the page text. If a value is not printed there, use null. "
    "Do not recompute totals or invent line items. "
    "document_type is purchase_order, invoice, or goods_receipt. "
    "document_date is YYYY-MM-DD or null. currency is a 3-letter code. "
    "quantity, unit_price, amount, subtotal, tax, and total are numbers or null."
)


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Completion:
    content: str
    input_tokens: int
    output_tokens: int


def ollama_complete(prompt: str) -> Completion:
    """One local model. Extra callers wait here instead of flooding Ollama."""
    with _model_slots():
        return _complete(prompt)


def _model_slots() -> threading.BoundedSemaphore:
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max(1, get_settings().ollama_max_in_flight))
        return _slots


def _complete(prompt: str) -> Completion:
    settings = get_settings()
    payload = _post(
        "/api/chat",
        {
            "model": settings.ollama_model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
        },
        CHAT_TIMEOUT,
    )
    message = payload.get("message") if isinstance(payload, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise OllamaError("Ollama returned an empty extraction.")
    return Completion(
        content=content,
        input_tokens=int(payload.get("prompt_eval_count") or 0),
        output_tokens=int(payload.get("eval_count") or 0),
    )


def _post(path: str, payload: dict, timeout: int) -> dict:
    settings = get_settings()
    url = settings.ollama_base_url.rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip().splitlines()
        reason = detail[-1][:240] if detail else exc.reason
        logger.warning("ollama request failed path=%s status=%s", path, exc.code)
        raise OllamaError(f"Ollama returned {exc.code}: {reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("ollama unreachable url=%s path=%s", settings.ollama_base_url, path)
        raise OllamaError(f"Ollama is not reachable at {settings.ollama_base_url}.") from exc
    except json.JSONDecodeError as exc:
        logger.warning("ollama returned non-json path=%s", path)
        raise OllamaError("Ollama returned a response that was not JSON.") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info("ollama request path=%s duration_ms=%s", path, duration_ms)
    if not isinstance(body, dict):
        raise OllamaError("Ollama returned a response that was not JSON.")
    return body
