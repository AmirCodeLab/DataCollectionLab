"""HTTP request/response logging (app/infrastructure/http_logging.py).

The middleware observes the request body on its way past. The tests that matter
are therefore: the endpoint still receives that body, secrets never reach the
log, and payloads cannot grow without bound.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from app.infrastructure.http_logging import _MAX_BODY_BYTES, HttpLoggingMiddleware


def _app(**options: Any) -> FastAPI:
    app = FastAPI()
    app.add_middleware(HttpLoggingMiddleware, **options)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, Any]:
        # Proves the endpoint still gets a body the middleware already read.
        # errors="replace" so a binary payload reaches here without exploding.
        return {"seen": (await request.body()).decode(errors="replace")}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("endpoint exploded")

    return app


def _call(app: FastAPI, method: str, url: str, **kwargs: Any) -> httpx.Response:
    async def main() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(main())


def test_the_endpoint_still_receives_a_body_the_logger_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"):
        response = _call(_app(), "POST", "/echo", json={"deviceId": "dev-a"})

    assert response.status_code == 200
    # The middleware must observe, never consume.
    assert json.loads(response.json()["seen"]) == {"deviceId": "dev-a"}

    logged = "\n".join(r.message for r in caplog.records)
    assert "POST /echo -> 200" in logged
    assert "dev-a" in logged, "request body is logged"
    assert "request headers:" in logged
    assert "response body:" in logged


def test_query_strings_are_logged_and_failures_are_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"):
        _call(_app(), "POST", "/echo?cursor=41&limit=200", content=b"{}")
        _call(_app(), "POST", "/missing", content=b"{}")

    logged = "\n".join(r.message for r in caplog.records)
    assert "/echo?cursor=41&limit=200" in logged
    assert "POST /missing -> 404" in logged
    levels = {r.message.split()[1]: r.levelno for r in caplog.records}
    assert levels["/missing"] == logging.WARNING, "a failed call stands out"
    assert levels["/echo?cursor=41&limit=200"] == logging.INFO


def test_secrets_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"):
        _call(
            _app(),
            "POST",
            "/echo",
            content=b"{}",
            headers={
                "Authorization": "Bearer super-secret-token",
                "Cookie": "session=secret-cookie",
                "X-Api-Key": "secret-key",
                "X-Trace-Id": "trace-123",
            },
        )

    logged = "\n".join(r.message for r in caplog.records)
    for secret in ("super-secret-token", "secret-cookie", "secret-key"):
        assert secret not in logged, f"{secret} leaked into the log"
    assert logged.count("<redacted>") >= 3
    assert "trace-123" in logged, "ordinary headers are still useful"


def test_bodies_can_be_switched_off_entirely(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"):
        _call(_app(log_bodies=False), "POST", "/echo", json={"answer": "respondent name"})

    logged = "\n".join(r.message for r in caplog.records)
    assert "POST /echo -> 200" in logged, "the request line survives"
    assert "respondent name" not in logged, "no payload when bodies are off"


def test_large_bodies_are_truncated(caplog: pytest.LogCaptureFixture) -> None:
    payload = json.dumps({"ops": ["x" * 50 for _ in range(500)]}).encode()
    assert len(payload) > _MAX_BODY_BYTES * 2

    with caplog.at_level(logging.INFO, logger="dcp.http"):
        response = _call(_app(), "POST", "/echo", content=payload,
                         headers={"Content-Type": "application/json"})

    assert len(response.json()["seen"]) == len(payload), "endpoint got all of it"
    logged = "\n".join(r.message for r in caplog.records)
    assert "truncated" in logged
    # The log line stays a log line, not a copy of the payload.
    assert len(logged) < len(payload)


def test_binary_bodies_are_summarised_not_dumped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"):
        _call(
            _app(), "POST", "/echo",
            content=b"\x89PNG\r\n\x1a\n\x00\x01\x02",
            headers={"Content-Type": "image/png"},
        )

    logged = "\n".join(r.message for r in caplog.records)
    assert "request body: <11 bytes of image/png>" in logged, logged


def test_an_exploding_endpoint_is_logged_and_still_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="dcp.http"), pytest.raises(RuntimeError):
        _call(_app(), "GET", "/boom")

    logged = "\n".join(r.message for r in caplog.records)
    assert "GET /boom -> 500" in logged
