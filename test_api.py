from conftest import API_KEY, post_reading


def test_health(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_dashboard_page_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Vital Touch" in res.data


def test_reading_requires_api_key(client):
    res = client.post("/api/readings", json={"device_id": "ESP32_01", "heart_rate": 75, "spo2": 98})
    assert res.status_code == 401
    res = client.post("/api/readings", json={"device_id": "ESP32_01", "heart_rate": 75, "spo2": 98},
                      headers={"X-API-Key": "wrong"})
    assert res.status_code == 401


def test_device_endpoint_disabled_without_configured_key(app, client):
    app.config["DEVICE_API_KEY"] = ""
    res = client.post("/api/readings", json={}, headers={"X-API-Key": ""})
    assert res.status_code == 503


def test_invalid_reading_rejected(client):
    res = post_reading(client, spo2=150)
    assert res.status_code == 400
    assert "spo2" in res.get_json()["details"][0]


def test_valid_reading_stored_with_status(client):
    res = post_reading(client, heart_rate=118, spo2=88)
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "critical"
    assert body["source"] == "device"
    assert body["temperature"] is None
    assert len(body["issues"]) == 2


def test_dashboard_data_requires_login(client):
    assert client.get("/api/readings").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/sos").status_code == 401


def test_login_rejects_wrong_password(client):
    res = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert res.status_code == 401


def test_login_disabled_without_configured_password(app, client):
    app.config["ADMIN_PASSWORD"] = ""
    res = client.post("/api/login", json={"username": "admin", "password": ""})
    assert res.status_code == 503


def test_polling_returns_only_new_readings(logged_in):
    for hr in (70, 80, 90):
        assert post_reading(logged_in, heart_rate=hr).status_code == 201

    all_rows = logged_in.get("/api/readings").get_json()["readings"]
    assert [r["heart_rate"] for r in all_rows] == [70, 80, 90]

    newer = logged_in.get(f"/api/readings?after_id={all_rows[0]['id']}").get_json()["readings"]
    assert [r["heart_rate"] for r in newer] == [80, 90]

    latest = logged_in.get("/api/readings/latest").get_json()["reading"]
    assert latest["heart_rate"] == 90


def test_sos_event_recorded(logged_in):
    res = logged_in.post("/api/sos", json={"message": "test SOS"})
    assert res.status_code == 201
    events = logged_in.get("/api/events").get_json()["events"]
    assert events[0]["message"] == "test SOS"
    assert events[0]["created_by"] == "admin"


def test_logout_ends_session(logged_in):
    logged_in.post("/api/logout")
    assert logged_in.get("/api/readings").status_code == 401
