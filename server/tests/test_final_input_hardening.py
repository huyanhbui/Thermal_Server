"""Regression: chặn boolean/NaN ở ranh giới HTTP và Settings trên disk."""
from __future__ import annotations

import json
import math
import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state
from settings import Settings


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _boot(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    client = TestClient(create_app(state))
    assert client.post("/api/room/bootstrap", json={
        "display_name": "A",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    }).status_code == 200
    joined = client.post("/join", json={
        "room_code": state.room.room_code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "W1",
        "capabilities": CAPS,
    })
    assert joined.status_code in (200, 201), joined.text
    admin = client.post("/join", json={
        "room_code": state.room.room_code,
        "password": "admin-pass-ok12",
        "role": "admin",
        "node_name": "Admin",
        "capabilities": CAPS,
    })
    assert admin.status_code in (200, 201), admin.text
    return state, client, joined.json()["token"], admin.json()["token"]


def test_ingest_rejects_boolean_metrics_before_sqlite_write(tmp_path):
    state, client, worker, _ = _boot(tmp_path)
    response = client.post("/ingest", headers=_auth(worker), json={
        "cpu_temp": True, "cpu_util": False, "power_w": True,
        "power_source": "sensor",
    })
    assert response.status_code == 422, response.text
    assert state.store.latest("W1") is None


def test_result_rejects_invalid_status_boolean_and_nonfinite_metrics(tmp_path):
    state, client, worker, _ = _boot(tmp_path)
    cases = [
        {"job_id": "missing", "status": "bogus"},
        {"job_id": "missing", "tokens_out": True},
        {"job_id": "missing", "peak_temp_c": "NaN"},
        {"job_id": "missing", "min_clock_mhz": "Infinity"},
        {"job_id": "missing", "prompt_eval_ms": "NaN"},
    ]
    for payload in cases:
        response = client.post("/jobs/result", headers=_auth(worker), json=payload)
        assert response.status_code == 422, (payload, response.status_code,
                                             response.text)
    assert state.store.esg_events() == []


def test_settings_rejects_nan_without_persisting_or_breaking_response(tmp_path):
    state, client, _, admin = _boot(tmp_path)
    path = tmp_path / "settings.json"
    before = state.settings.get()
    response = client.post("/api/settings", headers=_auth(admin), json={
        "w_cool": "NaN", "w_idle": 0.25, "w_power": 0.25,
        "w_load": 0.25,
    })
    assert response.status_code == 422, response.text
    assert state.settings.get() == before
    assert not path.exists(), "422 không được ghi settings.json"


def test_settings_sanitizes_nonfinite_value_loaded_from_disk(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"w_cool": NaN, "threshold_c": Infinity}',
                    encoding="utf-8")
    settings = Settings(str(path))
    values = settings.get()
    assert math.isfinite(values["w_cool"])
    assert math.isfinite(values["threshold_c"])
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert math.isfinite(persisted["w_cool"])
    assert math.isfinite(persisted["threshold_c"])
