# server/tests/test_main.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# We patch data functions so main.py loads without real FastF1 network calls
with patch('f1_data.fastf1'), patch('f1_data.requests'):
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
    assert response.headers.get("access-control-allow-origin") in (
        "http://localhost:5173", "*"
    )
