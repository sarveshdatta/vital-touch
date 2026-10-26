import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app  # noqa: E402

API_KEY = "test-device-key"


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "DEVICE_API_KEY": API_KEY,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "secret",
        "ADMIN_NAME": "Test Admin",
        "SECRET_KEY": "test",
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in(client):
    res = client.post("/api/login", json={"username": "admin", "password": "secret"})
    assert res.status_code == 200
    return client


def post_reading(client, **payload):
    body = {"device_id": "ESP32_01", "heart_rate": 75, "spo2": 98}
    body.update(payload)
    return client.post("/api/readings", json=body, headers={"X-API-Key": API_KEY})
