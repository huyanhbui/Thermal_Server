import os
os.environ["POC_NO_BACKGROUND"] = "1"
from fastapi.testclient import TestClient
from server import (ACTIVE_WINDOW_S, DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, STALE_AFTER_S, active_nodes,
                    build_state_payload, create_app, make_state,
                    run_forecast_cycle, run_scheduler_cycle)

def make_test_state(tmp_path):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "no_model.pkl"),
                      settings_path=str(tmp_path / "settings.json"),
                      esg_path=str(tmp_path / "esg.json"))

def _join(client, node_name=None, role="worker"):
    pw = (DEFAULT_ADMIN_PASSWORD if role == "admin"
          else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": DEFAULT_ROOM_CODE,
            "password": pw,
            "role": role}
    if role == "worker":
        body["node_name"] = node_name
        body["capabilities"] = {"cpu_cores": 4, "ram_gb": 8, "os": "test",
                                "has_gpu": False, "agent_version": "test"}
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]

def _auth(token):
    return {"Authorization": f"Bearer {token}"}

def seed_ramp(state, node, start_ts, start_temp, slope_per_min, n=10, step=10.0):
    """Write synthetic timeline directly to store.

    Ingest applies clock-skew correction against wall clock (docs/03 §4), so
    unit tests that need a controllable epoch (0..95) must seed the store —
    same samples the forecaster would see after a healthy agent session.
    """
    for i in range(n):
        ts = start_ts + i * step
        state.store.insert(
            node, ts,
            start_temp + slope_per_min * (i * step) / 60.0,
            None, 90.0, 40.0)

def test_full_loop_flags_hot_node_and_blocks_jobs(tmp_path):
    state = make_test_state(tmp_path)
    client = TestClient(create_app(state))
    tok_a = _join(client, "Node-A")
    tok_b = _join(client, "Node-B")
    seed_ramp(state, "Node-A", 0.0, 70.0, slope_per_min=6.0)
    seed_ramp(state, "Node-B", 0.0, 45.0, slope_per_min=0.0)
    now = 95.0
    preds = run_forecast_cycle(state, now=now)
    assert preds["Node-A"] > 75.0 and preds["Node-B"] < 75.0
    for _ in range(3):
        state.balancer.enqueue_job()
    run_scheduler_cycle(state, now=now)
    r = client.get("/jobs/next?wait=0", headers=_auth(tok_a))
    assert r.status_code == 204
    r = client.get("/jobs/next?wait=0", headers=_auth(tok_b))
    assert r.status_code == 200 and "duration_s" in r.json()
    payload = build_state_payload(state, now=now + 1.0)
    node_a = next(n for n in payload["nodes"] if n["name"] == "Node-A")
    assert node_a["flagged"] is True and node_a["predicted_max"] > 75.0
    assert "tier1_measured" in payload["esg"]
    assert "tier2_derived" in payload["esg"]
    assert "tier3_projected" in payload["esg"]

def test_cooled_node_gets_cleared(tmp_path):
    state = make_test_state(tmp_path)
    client = TestClient(create_app(state))
    _join(client, "Node-A")
    seed_ramp(state, "Node-A", 0.0, 70.0, slope_per_min=6.0)
    run_forecast_cycle(state, now=95.0)
    assert state.balancer.is_flagged("Node-A")
    seed_ramp(state, "Node-A", 100.0, 55.0, slope_per_min=-3.0)
    run_forecast_cycle(state, now=195.0)
    assert not state.balancer.is_flagged("Node-A")

def test_settings_roundtrip_and_validation(tmp_path):
    client = TestClient(create_app(make_test_state(tmp_path)))
    admin = _join(client, role="admin")
    assert client.get("/api/state", headers=_auth(admin)).json()["threshold_c"] == 75.0
    assert client.post("/api/settings", headers=_auth(admin),
                       json={"threshold_c": 80}).status_code == 200
    assert client.get("/api/state", headers=_auth(admin)).json()["threshold_c"] == 80.0
    assert client.post("/api/settings", headers=_auth(admin),
                       json={"threshold_c": 20}).status_code == 422

def test_ingest_validates_node_and_csv_export(tmp_path):
    client = TestClient(create_app(make_test_state(tmp_path)))
    # Without token → 401 (S1 / S15); body without auth no longer 422 on node.
    assert client.post("/ingest", json={"cpu_temp": 50}).status_code == 401
    admin = _join(client, role="admin")
    r = client.get("/api/esg.csv", headers=_auth(admin))
    assert r.status_code == 200 and "event" in r.text
    r2 = client.get("/api/esg/report.csv", headers=_auth(admin))
    assert r2.status_code == 200 and "tier" in r2.text

def test_stale_flagged_node_gets_cleared_and_stops_accruing_esg(tmp_path):
    # Contract: stuck flag clears when agent dies; không cộng ESG giả vô hạn.
    from esg import compute_report
    state = make_test_state(tmp_path)
    client = TestClient(create_app(state))
    _join(client, "Node-A")
    seed_ramp(state, "Node-A", 0.0, 70.0, slope_per_min=6.0)
    run_forecast_cycle(state, now=95.0)
    assert state.balancer.is_flagged("Node-A")
    events_while = state.store.esg_events()
    assert any(e["event_type"] == "flagged" for e in events_while)

    stale_now = 95.0 + 200.0
    assert stale_now - 90.0 > STALE_AFTER_S
    preds = run_forecast_cycle(state, now=stale_now)
    assert preds["Node-A"] is None
    assert not state.balancer.is_flagged("Node-A")

    # Báo cáo từ ledger ổn định theo thời gian tường (E10) — không phụ thuộc now
    r1 = compute_report(state.store.esg_events(), state.esg.config, stale_now)
    r2 = compute_report(state.store.esg_events(), state.esg.config,
                        stale_now + 3600.0)
    assert r1["tier1_measured"] == r2["tier1_measured"]

def test_ghost_node_from_old_session_excluded_from_active_state(tmp_path):
    # Contract: telemetry older than ACTIVE_WINDOW_S is invisible.
    state = make_test_state(tmp_path)
    client = TestClient(create_app(state))
    now = 100000.0
    old_ts = now - ACTIVE_WINDOW_S - 60.0
    # Seed old rows directly — ghost predates join/auth.
    state.store.insert("Node-Old", old_ts, 30.0, None, 5.0, 10.0)
    _join(client, "Node-Fresh")
    seed_ramp(state, "Node-Fresh", now - 90.0, 60.0, slope_per_min=0.0)

    active = active_nodes(state, now)
    assert "Node-Fresh" in active and "Node-Old" not in active

    payload = build_state_payload(state, now)
    names = [n["name"] for n in payload["nodes"]]
    assert "Node-Fresh" in names and "Node-Old" not in names

    preds = run_forecast_cycle(state, now)
    assert "Node-Old" not in preds and "Node-Fresh" in preds
