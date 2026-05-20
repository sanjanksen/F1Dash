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


def test_drivers_endpoint_returns_type_in_detail():
    def _boom():
        raise FileNotFoundError("C:\\Users\\secret\\cache\\drivers.csv missing")

    with patch("main.get_drivers", side_effect=_boom):
        response = client.get("/api/drivers")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "FileNotFoundError" in detail
    assert "C:\\" not in detail
    assert "/usr/" not in detail
    assert "secret" not in detail


def test_circuits_endpoint_does_not_leak_exception_message():
    def _boom():
        raise ConnectionError("super-secret-host:5432 unreachable")

    with patch("main.get_circuits", side_effect=_boom):
        response = client.get("/api/circuits")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "ConnectionError" in detail
    assert "super-secret-host" not in detail
    assert "5432" not in detail


def test_chat_endpoint_returns_type_in_detail():
    def _boom(*args, **kwargs):
        raise RuntimeError("internal-token=abc123 leaked path /var/secrets")

    with patch("main.answer_f1_payload", side_effect=_boom):
        response = client.post("/api/chat", json={"message": "tell me"})

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "RuntimeError" in detail
    assert "internal-token" not in detail
    assert "/var/secrets" not in detail
