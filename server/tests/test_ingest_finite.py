"""P2: IngestBody từ chối NaN/Infinity/âm; raw JSON regression."""
from __future__ import annotations

import json
import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _boot(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    assert c.post("/api/room/bootstrap", json={
        "display_name": "A",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    }).status_code == 200
    r = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "W1",
        "capabilities": CAPS,
    })
    assert r.status_code in (200, 201)
    return state, c, r.json()["token"]


def test_ingest_rejects_nan_infinity_negative_raw_json(tmp_path):
    state, c, tok = _boot(tmp_path)
    cases = [
        {"cpu_temp": "NaN", "power_source": "none"},
        {"cpu_util": "Infinity", "power_source": "none"},
        {"power_w": -1, "power_source": "sensor"},
        {"ts": "NaN", "cpu_temp": 40.0, "power_source": "none"},
    ]
    for payload in cases:
        body = json.dumps(payload)
        r = c.post(
            "/ingest",
            headers={**_auth(tok), "Content-Type": "application/json"},
            content=body.encode("utf-8"),
        )
        assert r.status_code in (400, 422), (payload, r.status_code, r.text)
        latest = state.store.latest("W1")
        assert latest is None or latest.get("cpu_temp") != "NaN"
