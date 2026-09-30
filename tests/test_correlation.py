from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app
from app.middleware import resolve_correlation_id
from app.pii import hash_user_id


def test_resolve_correlation_id_accepts_only_req_plus_8_hex() -> None:
    assert resolve_correlation_id("req-abc12345") == "req-abc12345"
    assert resolve_correlation_id("  req-ABC12345  ") == "req-ABC12345"
    generated = resolve_correlation_id(None)
    assert re.fullmatch(r"req-[0-9a-f]{8}", generated)
    assert resolve_correlation_id("MISSING") != "MISSING"
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id("req-short"))


def test_chat_binds_correlation_metadata_and_scrubs_pii(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/chat",
                headers={"x-request-id": "req-abc12345"},
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Email student@vinuni.edu.vn and CCCD 079203001234",
                },
            )
            second = await client.post(
                "/chat",
                json={
                    "user_id": "student-02",
                    "session_id": "session-02",
                    "feature": "summary",
                    "message": "Phone 0901234567 and card 4111 1111 1111 1111",
                },
            )
            return first, second

    first, second = asyncio.run(send())
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-request-id"] == "req-abc12345"
    assert first.json()["correlation_id"] == "req-abc12345"
    assert re.fullmatch(r"req-[0-9a-f]{8}", second.headers["x-request-id"])
    assert float(first.headers["x-response-time-ms"]) >= 0

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "079203001234" not in raw
    assert "0901234567" not in raw
    assert "4111 1111 1111 1111" not in raw
    assert "4111111111111111" not in raw

    first_logs = [event for event in events if event.get("correlation_id") == "req-abc12345"]
    second_logs = [event for event in events if event.get("correlation_id") == second.headers["x-request-id"]]
    assert first_logs and second_logs
    assert all(event["user_id_hash"] == hash_user_id("student-01") for event in first_logs if event.get("service") == "api")
    assert all(event["session_id"] == "session-02" for event in second_logs if event.get("service") == "api")
    assert all(event["feature"] == "summary" for event in second_logs if event.get("service") == "api")
    assert all(event["model"] == "claude-sonnet-4-5" for event in second_logs if event.get("service") == "api")
    assert all(event["env"] == "dev" for event in second_logs if event.get("service") == "api")
    response_event = next(event for event in first_logs if event["event"] == "response_sent")
    received = next(event for event in first_logs if event["event"] == "request_received")
    assert "retrieval_ms" in response_event
    assert "generation_ms" in response_event
    assert "REDACTED_EMAIL" in received["payload"]["message_preview"]
    assert "REDACTED_CCCD" in received["payload"]["message_preview"]
