"""One log line per HTTP request: method, path, status, and duration."""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

# The process health check runs every few seconds. Keep it out of the normal log.
_QUIET_PATHS = {"/health"}


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "request failed method=%s path=%s duration_ms=%s",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        line = "request method=%s path=%s status=%s duration_ms=%s"
        args = (request.method, request.url.path, response.status_code, duration_ms)
        if request.url.path in _QUIET_PATHS:
            logger.debug(line, *args)
        elif response.status_code >= 500:
            logger.error(line, *args)
        elif response.status_code >= 400:
            logger.warning(line, *args)
        else:
            logger.info(line, *args)
        return response
