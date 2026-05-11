import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_header_present():
    response = client.options(
        "/api/drivers",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def _parse_sse_events(raw_bytes: bytes) -> list[dict]:
    text = raw_bytes.decode()
    events = []
    for part in text.split("\n\n"):
        part = part.strip()
        if part.startswith("data: "):
            events.append(json.loads(part[6:]))
    return events


def test_chat_endpoint_streams_sse():
    """The /api/chat endpoint emits SSE events: delta chunks then a done event."""

    def fake_streaming(message, history):
        yield 'data: {"type":"delta","text":"Verstappen"}\n\n'
        yield 'data: {"type":"delta","text":" leads."}\n\n'
        yield 'data: {"type":"done","text":"Verstappen leads.","widgets":[]}\n\n'

    with patch("main.answer_f1_payload_streaming", side_effect=fake_streaming):
        with client.stream("POST", "/api/chat", json={"message": "Who is leading?"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            raw = b"".join(r.iter_bytes())

    events = _parse_sse_events(raw)
    assert events[0] == {"type": "delta", "text": "Verstappen"}
    assert events[1] == {"type": "delta", "text": " leads."}
    assert events[2]["type"] == "done"
    assert events[2]["text"] == "Verstappen leads."
    assert events[2]["widgets"] == []


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
