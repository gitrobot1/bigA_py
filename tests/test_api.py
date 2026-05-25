import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "database_ok" in data
    assert "quote_count" in data


def test_market_summary():
    response = client.get("/api/v1/market/summary")
    assert response.status_code == 200
    data = response.json()
    assert "indices" in data
    assert "poll_interval_seconds" in data


def test_users_me_unauthorized():
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
