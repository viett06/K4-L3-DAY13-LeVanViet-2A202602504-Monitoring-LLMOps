import json

from app.logging_config import scrub_event


def test_scrub_event_redacts_nested_payload_before_render() -> None:
    event = {
        "event": "request_received",
        "payload": {
            "message_preview": "student@vinuni.edu.vn CCCD 079203001234",
            "notes": ["Passport B1234567", {"address": "Số nhà 25 đường Lê Lợi"}],
        },
    }

    scrubbed = scrub_event(None, "info", event)
    raw = json.dumps(scrubbed, ensure_ascii=False)

    assert "student@" not in raw
    assert "079203001234" not in raw
    assert "B1234567" not in raw
    assert "Lê Lợi" not in raw
    assert "REDACTED_EMAIL" in raw
    assert "REDACTED_CCCD" in raw
    assert "REDACTED_PASSPORT" in raw
    assert "REDACTED_VN_ADDRESS" in raw
