"""Regression seams for real worker readiness and chat dispatch.

These tests exercise the public HTTP boundary instead of implementation
details so a dashboard cannot report a model usable before the agent has
loaded the selected room model.
"""
from __future__ import annotations

import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state, run_forecast_cycle


def _state(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_password="worker-password-123",
        admin_password="admin-password-123",
        credentials_weak=False,
    )
    return state


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _join(client, *, role, node_name=None):
    payload = {
        "room_code": "THERMAL-LOCAL",
        "password": ("admin-password-123" if role == "admin"
                     else "worker-password-123"),
        "role": role,
    }
    if node_name:
        payload["node_name"] = node_name
        payload["capabilities"] = {"cpu_cores": 4, "ram_gb": 8}
    response = client.post("/join", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _seed_telemetry(state, node, now=100.0):
    for offset in range(10):
        state.store.insert(
            node, now - 90 + offset * 10, 45.0, None, 10.0, 20.0)
    run_forecast_cycle(state, now)


def test_joined_worker_remains_not_ready_until_it_reports_exact_model(tmp_path):
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    worker = _join(client, role="worker", node_name="Node-A")

    _seed_telemetry(state, "Node-A")

    assert state.forecast_cache.get("Node-A").model_ready is False
    response = client.post(
        "/nodes/ready", headers=_auth(worker),
        json={"runtime_ready": True, "model_id": "wrong-model"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_MISMATCH"


def test_chat_fails_fast_when_no_exact_model_is_ready(tmp_path):
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    admin = _join(client, role="admin")
    _join(client, role="worker", node_name="Node-A")
    _seed_telemetry(state, "Node-A")

    response = client.post(
        "/chat", headers=_auth(admin), json={"prompt": "Xin chào"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_LLM_READY"


def test_stale_but_pinned_worker_cannot_make_chat_look_dispatchable(tmp_path):
    """Readiness model còn đúng không bù được telemetry đã STALE."""
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    admin = _join(client, role="admin")
    worker = _join(client, role="worker", node_name="Node-A")
    _seed_telemetry(state, "Node-A")
    selected = state.settings.get()["model_id"]
    from room_assets import RUNTIME_ID, get_model

    ready = client.post("/nodes/ready", headers=_auth(worker), json={
        "runtime_ready": True,
        "model_id": selected,
        "model_sha256": get_model(selected)["sha256"],
        "model_generation": 0,
        "runtime_id": RUNTIME_ID,
    })
    assert ready.status_code == 200
    state.forecast_cache.patch("Node-A", state="STALE")

    response = client.post("/chat", headers=_auth(admin),
                           json={"prompt": "không được treo"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_LLM_READY"


def test_worker_stream_chunk_is_forwarded_to_admin_websocket(tmp_path):
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    admin = _join(client, role="admin")
    worker = _join(client, role="worker", node_name="Node-A")
    selected = state.settings.get()["model_id"]
    from room_assets import RUNTIME_ID, get_model

    ready = client.post(
        "/nodes/ready", headers=_auth(worker),
        json={
            "runtime_ready": True,
            "model_id": selected,
            "model_sha256": get_model(selected)["sha256"],
            "model_generation": 0,
            "runtime_id": RUNTIME_ID,
        },
    )
    assert ready.status_code == 200, ready.text
    _seed_telemetry(state, "Node-A")
    queued = client.post(
        "/chat", headers=_auth(admin),
        json={"prompt": "stream", "stream": True},
    )
    assert queued.status_code == 202, queued.text
    from server import run_scheduler_cycle

    run_scheduler_cycle(state, 100.0)
    claimed = client.get("/jobs/next?wait=0", headers=_auth(worker)).json()

    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": admin})
        socket.receive_json()
        event = client.post(
            f"/jobs/{claimed['id']}/events", headers=_auth(worker),
            json={"attempt_id": claimed["attempt_id"], "seq": 0,
                  "delta": "Xin chào"},
        )
        assert event.status_code == 202, event.text
        pushed = socket.receive_json()
        assert pushed == {
            "type": "chat_token", "job_id": claimed["id"],
            "attempt_id": claimed["attempt_id"], "seq": 0,
            "delta": "Xin chào",
        }


def test_bootstrap_starts_the_local_host_agent_through_launcher_seam(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("server._local_agent_process_running", lambda: False)
    state = make_state(
        db_path=":memory:", model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"), bootstrap_open=True,
    )
    launched = []
    state.local_agent_launcher = lambda _state, node: launched.append(node)
    client = TestClient(create_app(state))

    response = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": "worker-password-123",
        "admin_password": "admin-password-123", "host_contributes": True,
    })

    assert response.status_code == 200, response.text
    assert launched == [response.json()["room"]["local_agent"]["node"]]
    assert response.json()["room"]["local_agent"]["state"] == "awaiting_uac"
