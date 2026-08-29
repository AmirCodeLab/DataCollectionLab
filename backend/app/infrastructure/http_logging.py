"""Request/response logging for development.

Logs every endpoint hit: method, URL, headers, request body, response status
and response body, plus how long it took. Written for the moment a field
client reports "sync failed" and you need to see exactly what crossed the wire.

Two deliberate constraints:

- **Off unless switched on.** Submissions carry respondent data, so logging
  bodies is a privacy decision, not a convenience. The default follows
  `environment == "development"`; `http_log_bodies=false` keeps the request
  line but drops payloads.
- **Secrets are redacted, always** — Authorization, Cookie and similar headers
  never reach the log, in any environment.

Implemented as raw ASGI rather than BaseHTTPMiddleware: the request body has to
be observed while still being delivered to the endpoint, and Starlette's
higher-level middleware consumes the stream to do that.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

logger = logging.getLogger("dcp.http")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

# Never logged, at any level, in any environment.
_REDACTED_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}
)

# Bodies are truncated: one 500-op push batch would otherwise bury the log.
_MAX_BODY_BYTES = 4096

_TEXTUAL_TYPES = ("application/json", "text/", "application/x-www-form-urlencoded", "+json")


def configure_logging(level: int = logging.INFO) -> None:
    """Give `dcp.http` a handler of its own.

    uvicorn installs handlers only on its own loggers and leaves the root
    logger bare, so an INFO record from this module would otherwise fall
    through to logging's lastResort handler and be dropped for being below
    WARNING — the logs would simply never appear.
    """
    log = logging.getLogger("dcp")
    log.setLevel(level)
    if not any(getattr(h, "_dcp_http", False) for h in log.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        handler._dcp_http = True  # type: ignore[attr-defined]  # idempotence marker
        log.addHandler(handler)
    # Root may gain handlers later (pytest, a production config); without this
    # every request would then be logged twice.
    log.propagate = False


def _headers(raw: list[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in raw:
        name = key.decode("latin-1").lower()
        out[name] = "<redacted>" if name in _REDACTED_HEADERS else value.decode("latin-1")
    return out


def _body(raw: bytes, content_type: str) -> str:
    if not raw:
        return ""
    if not any(t in content_type.lower() for t in _TEXTUAL_TYPES):
        return f"<{len(raw)} bytes of {content_type or 'unknown type'}>"
    clipped = raw[:_MAX_BODY_BYTES]
    try:
        text = clipped.decode("utf-8")
    except UnicodeDecodeError:
        return f"<{len(raw)} undecodable bytes>"
    if len(raw) > _MAX_BODY_BYTES:
        text += f"... <truncated, {len(raw)} bytes total>"
    return text


def _pretty(text: str) -> str:
    """Re-indent JSON so a body is readable in a terminal; leave anything else."""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return text


class HttpLoggingMiddleware:
    """Logs one block per request. See module docstring for the guarantees."""

    def __init__(self, app: Any, *, log_bodies: bool = True, pretty: bool = True) -> None:
        self.app = app
        self.log_bodies = log_bodies
        self.pretty = pretty

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not logger.isEnabledFor(logging.INFO):
            await self.app(scope, receive, send)
            return

        request_chunks: list[bytes] = []

        async def receive_logging() -> Message:
            message = await receive()
            if message["type"] == "http.request" and self.log_bodies:
                chunk = message.get("body", b"")
                # Cap what we retain; a large upload must not be buffered whole.
                if chunk and sum(map(len, request_chunks)) < _MAX_BODY_BYTES * 2:
                    request_chunks.append(chunk)
            return message

        status = 0
        response_headers: list[tuple[bytes, bytes]] = []
        response_chunks: list[bytes] = []

        async def send_logging(message: Message) -> None:
            nonlocal status, response_headers
            if message["type"] == "http.response.start":
                status = int(message["status"])
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body" and self.log_bodies:
                chunk = message.get("body", b"")
                if chunk and sum(map(len, response_chunks)) < _MAX_BODY_BYTES * 2:
                    response_chunks.append(chunk)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive_logging, send_logging)
        except Exception:
            # The endpoint blew up: log what we have, then let it propagate so
            # the error response and stack trace are still Starlette's job.
            self._emit(scope, request_chunks, 500, [], [], time.perf_counter() - started)
            raise
        self._emit(
            scope, request_chunks, status, response_headers, response_chunks,
            time.perf_counter() - started,
        )

    def _emit(
        self,
        scope: Scope,
        request_chunks: list[bytes],
        status: int,
        response_headers: list[tuple[bytes, bytes]],
        response_chunks: list[bytes],
        elapsed: float,
    ) -> None:
        request_headers = _headers(list(scope.get("headers", [])))
        query = scope.get("query_string", b"").decode("latin-1")
        path = scope.get("path", "")
        url = f"{path}?{query}" if query else path
        method = scope.get("method", "?")

        lines = [
            f"{method} {url} -> {status} ({elapsed * 1000:.0f}ms)",
            f"  request headers: {json.dumps(request_headers)}",
        ]
        if self.log_bodies:
            body = _body(b"".join(request_chunks), request_headers.get("content-type", ""))
            if body:
                lines.append(f"  request body: {self._render(body)}")
            out_headers = _headers(response_headers)
            if out_headers:
                lines.append(f"  response headers: {json.dumps(out_headers)}")
            out = _body(b"".join(response_chunks), out_headers.get("content-type", ""))
            if out:
                lines.append(f"  response body: {self._render(out)}")

        # A failed call is what someone is hunting for; make it visible.
        logger.log(logging.WARNING if status >= 400 else logging.INFO, "\n".join(lines))

    def _render(self, text: str) -> str:
        if not self.pretty:
            return text
        rendered = _pretty(text)
        return rendered if "\n" not in rendered else "\n    " + rendered.replace("\n", "\n    ")
