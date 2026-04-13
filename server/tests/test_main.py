# server/tests/test_main.py
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


def test_chat_endpoint_returns_response():
    with patch("main.answer_f1_payload", return_value={"response": "Verstappen leads.", "widgets": []}):
        response = client.post("/api/chat", json={"message": "Who is leading?"})

    assert response.status_code == 200
    assert response.json() == {"response": "Verstappen leads.", "widgets": []}


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
