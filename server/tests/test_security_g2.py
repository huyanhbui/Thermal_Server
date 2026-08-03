"""Ca bảo mật G2 — energy_source, long-poll limit, kick/leave."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

import asyncio
import time
from fastapi.testclient import TestClient

from forecast_cache import NodeForecast
from scheduler import DEFAULT_WEIGHTS, schedule_once
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, create_app, make_state,
                    run_forecast_cycle, run_scheduler_cycle,
                    _release_node_work)


def _state(tmp_path):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "no_model.pkl"),
                      settings_path=str(tmp_path / "settings.json"),
                      esg_path=str(tmp_path / "esg.json"))


def _join(client, name="Node-A", role="worker"):
    pw = (DEFAULT_ADMIN_PASSWORD if role == "admin"
          else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": DEFAULT_ROOM_CODE,
            "password": pw, "role": role}
    if role == "worker":
        body["node_name"] = name
        body["capabilities"] = {"cpu_cores": 4, "ram_gb": 8, "os": "t",
                                "has_gpu": False, "agent_version": "t"}
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_ready(state, name, now=100.0):
    for i in range(10):
        state.store.insert(name, now - 90 + i * 10, 45.0, None, 10.0, 20.0)
    run_forecast_cycle(state, now)


def test_jobs_result_rejects_bogus_energy_source(tmp_path):
    """energy_source=sensor không có energy_j → 422."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")
    _seed_ready(state, "Node-A")
    state.balancer.enqueue_job()
    run_scheduler_cycle(state, 100.0)
    job = c.get("/jobs/next?wait=0", headers=_auth(tok)).json()
    r = c.post("/jobs/result", headers=_auth(tok),
               json={"job_id": job["id"], "status": "ok",
                     "energy_source": "sensor"})
    assert r.status_code == 422
    r2 = c.post("/jobs/result", headers=_auth(tok),
                json={"job_id": job["id"], "status": "ok",
                      "energy_source": "none"})
    assert r2.status_code == 200


def test_second_long_poll_returns_429(tmp_path):
    """Hai long-poll cùng token → 429 TOO_MANY_POLLS."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")
    auth = state.room.resolve(tok)
    state._job_polls.add(auth.token_hash)
    r = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "TOO_MANY_POLLS"
    state._job_polls.discard(auth.token_hash)
    r2 = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert r2.status_code == 204


def test_kick_does_not_requeue_active_job(tmp_path):
    """Claim rồi kick → job không về pending."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")
    admin = _join(c, role="admin")
    _seed_ready(state, "Node-A")
    job = state.balancer.enqueue_job()
    run_scheduler_cycle(state, 100.0)
    claimed = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert claimed.status_code == 200
    jid = claimed.json()["id"]
    r = c.post(f"/api/nodes/Node-A/kick", headers=_auth(admin))
    assert r.status_code == 200
    assert r.json().get("cancelled_job") == jid
    assert all(j["id"] != jid for j in state.balancer.pending())
    assert state.balancer.get_failed(jid) is not None


def test_leave_releases_reservation(tmp_path):
    """Reserve rồi leave → job về pending, inflight 0."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")
    _seed_ready(state, "Node-A")
    job = state.balancer.enqueue_job()
    run_scheduler_cycle(state, 100.0)
    assert state.balancer.reserved()
    assert state.forecast_cache.get("Node-A").inflight == 1
    r = c.post("/leave", headers=_auth(tok))
    assert r.status_code == 200
    pending = state.balancer.pending()
    assert any(j["id"] == job["id"] for j in pending)
    assert state.forecast_cache.get("Node-A").inflight == 0
    assert state.forecast_cache.get("Node-A").state == "INACTIVE"


def test_kick_marks_inactive_no_reflag(tmp_path):
    """Sau kick, forecast không gắn cờ lại từ mẫu cũ."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    _join(c, "Node-A")
    admin = _join(c, role="admin")
    # seed nóng
    for i in range(10):
        state.store.insert("Node-A", i * 10.0, 70.0 + i, None, 90.0, 50.0)
    run_forecast_cycle(state, 95.0)
    assert state.balancer.is_flagged("Node-A")
    c.post("/api/nodes/Node-A/kick", headers=_auth(admin))
    assert state.forecast_cache.get("Node-A").state == "INACTIVE"
    run_forecast_cycle(state, 100.0)
    assert state.forecast_cache.get("Node-A").state == "INACTIVE"
    assert not state.balancer.is_flagged("Node-A")


def test_r6_release_reservation_only_not_active():
    """Ca R6 — chỉ reservation về hàng đợi; active thì cancel."""
    now = 1000.0
    from balancer import LoadBalancer
    q = LoadBalancer()
    cache = {
        "Node-A": NodeForecast(
            node="Node-A", state="READY", predicted_max_c=50.0,
            current_temp_c=40.0, cpu_util=5.0, power_w=18.0,
            power_source="sensor", last_sample_ts=now,
            idle_baseline_c=35.0, effective_threshold_c=75.0),
    }
    job = q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    released = q.release_reservations_for("Node-A")
    assert job["id"] in released
    assert q.pending()[0]["id"] == job["id"]

    # Active path
    q2 = LoadBalancer()
    job2 = q2.enqueue_job()
    schedule_once(
        {"Node-A": NodeForecast(
            node="Node-A", state="READY", predicted_max_c=50.0,
            current_temp_c=40.0, cpu_util=5.0, power_w=18.0,
            power_source="sensor", last_sample_ts=now,
            idle_baseline_c=35.0, effective_threshold_c=75.0)},
        q2, DEFAULT_WEIGHTS, now)
    q2.claim("Node-A", now=now)
    assert q2.release_reservations_for("Node-A") == []
    cancelled = q2.cancel_active("Node-A")
    assert cancelled["id"] == job2["id"]
    assert q2.pending() == []
