"""Client weather ingest — API key never reaches the server."""
from __future__ import annotations

import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ROOM_CODE,
    DEFAULT_ROOM_PASSWORD,
    create_app,
    make_state,
)
from weather import WeatherService, apply_weather_to_esg


def _state(tmp_path):
    return make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "no_model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        weather_path=str(tmp_path / "weather_local.json"),
    )


def _join(client, role="admin"):
    pw = (DEFAULT_ADMIN_PASSWORD if role == "admin"
          else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": DEFAULT_ROOM_CODE, "password": pw, "role": role}
    if role == "worker":
        body["node_name"] = "Node-A"
        body["capabilities"] = {
            "cpu_cores": 4, "ram_gb": 8, "os": "t",
            "has_gpu": False, "agent_version": "t",
        }
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_ingest_client_reading_updates_snapshot_and_esg(tmp_path):
    svc = WeatherService(config_path=str(tmp_path / "missing.json"))
    entry = svc.ingest_client_reading(
        temp_c=31.5, feels_like_c=36.0, lat=21.0, lon=105.8,
        now=1000.0, label="Office", source="owm_gps")
    assert entry["temp_c"] == 31.5
    snap = svc.snapshot(1000.0)
    assert "gps-host" in snap
    assert snap["gps-host"]["source"] == "owm_gps"
    assert snap["gps-host"]["lat"] == 21.0
    cfg = {"outdoor_temp_c": None, "cooling_weather_k": 0.02}
    apply_weather_to_esg(svc, cfg, site_id="gps-host", now=1000.0)
    assert cfg["outdoor_temp_c"] == 31.5


def test_post_weather_reading_admin_only(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, "admin")
    worker = _join(c, "worker")
    body = {
        "temp_c": 28.0, "feels_like_c": 30.0,
        "lat": 10.7, "lon": 106.6, "label": "HCM",
        "source": "owm_gps",
    }
    bad = c.post("/api/weather/reading",
                 headers={"Authorization": f"Bearer {worker}"}, json=body)
    assert bad.status_code == 403
    ok = c.post("/api/weather/reading",
                headers={"Authorization": f"Bearer {admin}"}, json=body)
    assert ok.status_code == 200, ok.text
    reading = ok.json()["reading"]
    assert reading["temp_c"] == 28.0
    assert reading["source"] == "owm_gps"
    st = c.get("/api/state", headers={"Authorization": f"Bearer {admin}"})
    assert st.status_code == 200
    weather = st.json().get("weather") or {}
    assert any(v.get("temp_c") == 28.0 for v in weather.values())


def test_invite_has_no_fake_qr_svg(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, "admin")
    r = c.get("/api/room/invite",
              headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200
    assert "qr_svg_data_url" not in r.json()
    room = r.json()["room"]
    assert "invite_lan" in room
