"""Nợ review G4+: lease active, validate energy, Tầng 2, mode/quota/pwd, CSV."""
import math
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from esg import compute_report
from errors import ApiError
from room import Room
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, apply_job_result, create_app,
                    make_state, run_scheduler_cycle)


def _state(tmp_path):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "m.pkl"),
                      settings_path=str(tmp_path / "s.json"),
                      esg_path=str(tmp_path / "e.json"))


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
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_ready(state, name, now=100.0, temp=45.0):
    from server import run_forecast_cycle
    for i in range(10):
        state.store.insert(name, now - 90 + i * 10, temp, None, 10.0, 20.0)
    run_forecast_cycle(state, now)
    from room_assets import RUNTIME_ID, get_model
    model = get_model(state.settings.get()["model_id"])
    state.forecast_cache.patch(
        name, model_ready=True, model_id=model["model_id"],
        model_sha256=model["sha256"], model_generation=state.llm_generation,
        runtime_id=RUNTIME_ID)


def test_r2_chat_lease_expires_requeues_to_queued(tmp_path):
    """Claim với now giả — HTTP /jobs/next dùng time.time() thật."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    _join(c, "Node-A")
    _seed_ready(state, "Node-A", now=100.0)
    jid = c.post("/chat", headers=_auth(admin),
                 json={"prompt": "lease"}).json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    claimed = state.balancer.claim("Node-A", now=100.0)
    assert claimed is not None and claimed["id"] == jid
    state.chat.mark_running(jid, "Node-A", now=100.0)
    assert c.get(f"/chat/{jid}", headers=_auth(admin)).json()["status"] == (
        "running")
    # Nhảy quá active_deadline được suy ra từ max_tokens của chat.
    run_scheduler_cycle(state, claimed["active_deadline"] + 1.0)
    g = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g["status"] == "queued"
    # Kết quả muộn → ignored
    late = apply_job_result(state, "Node-A", {
        "job_id": jid, "status": "ok", "text": "late",
        "energy_source": "none", "tokens_out": 1,
    }, 162.0)
    assert late.get("ignored") is True


def test_r3_negative_or_nan_energy_rejected(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    jid = c.post("/chat", headers=_auth(admin),
                 json={"prompt": "energy"}).json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    assert state.balancer.claim("Node-A", now=100.0) is not None
    bad = c.post("/jobs/result", headers=_auth(tok),
                 json={"job_id": jid, "status": "ok",
                       "energy_source": "sensor", "energy_j": -1,
                       "tokens_out": 10})
    assert bad.status_code == 422
    assert not any(e["event_type"] == "job_completed"
                   for e in state.store.esg_events())
    # Job vẫn active — nan cũng 422 (gọi trực tiếp, JSON không serialize nan)
    try:
        apply_job_result(state, "Node-A", {
            "job_id": jid, "status": "ok",
            "energy_source": "sensor", "energy_j": math.nan,
            "tokens_out": 10,
        }, 101.0)
        assert False, "expected ApiError"
    except ApiError as e:
        assert e.status == 422
    assert not any(e["event_type"] == "job_completed"
                   for e in state.store.esg_events())


def test_r4_tier2_leakage_from_delta_t_and_duration():
    leakage_w = 0.18
    # ΔT=5°C, duration 1h → 5*0.18*1/1000 = 0.0009 kWh
    events = [{
        "ts": 1, "node": "A", "event_type": "job_completed",
        "detail": {
            "status": "ok", "energy_source": "sensor",
            "energy_j": 100.0, "tokens_out": 50,
            "scheduler_mode": "thermal_aware",
            "delta_t_avoided_c": 5.0, "duration_h": 1.0,
        },
    }]
    r = compute_report(events, {"leakage_w_per_c": leakage_w})
    assert abs(r["tier2_derived"]["kwh_leakage_saved"] - 0.0009) < 1e-12


def test_r4_tier2_missing_fields_zero_with_assumption():
    events = [{
        "ts": 1, "node": "A", "event_type": "job_completed",
        "detail": {
            "status": "ok", "energy_source": "sensor",
            "energy_j": 100.0, "tokens_out": 50,
            "scheduler_mode": "thermal_aware",
        },
    }]
    # Cần leakage đo được thì mới báo thiếu ΔT (null → assumption chưa đo)
    r = compute_report(events, {"leakage_w_per_c": 0.18})
    assert r["tier2_derived"]["kwh_leakage_saved"] == 0.0
    assert any("thiếu ΔT" in a for a in r["tier2_derived"]["assumptions"])


def test_r4_e13_flagging_still_does_not_change_jpt():
    base = [{
        "ts": 1, "node": "A", "event_type": "job_completed",
        "detail": {
            "status": "ok", "energy_source": "sensor",
            "energy_j": 100.0, "tokens_out": 50,
            "scheduler_mode": "thermal_aware",
            "delta_t_avoided_c": 2.0, "duration_h": 0.1,
        },
    }]
    flagged = base + [
        {"ts": 2, "node": "A", "event_type": "flagged", "detail": {}},
    ]
    assert (compute_report(base)["tier1_measured"]["j_per_token"]
            == compute_report(flagged)["tier1_measured"]["j_per_token"])


def test_y1_scheduler_mode_stamped_at_assign(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    state.settings.set_scheduler_mode("thermal_aware")
    jid = c.post("/chat", headers=_auth(admin),
                 json={"prompt": "mode"}).json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    assert c.get("/jobs/next?wait=0", headers=_auth(tok)).status_code == 200
    # Đổi mode trước khi result — event phải giữ mode lúc gán
    state.settings.set_scheduler_mode("round_robin")
    out = apply_job_result(state, "Node-A", {
        "job_id": jid, "status": "ok", "text": "ok",
        "energy_source": "sensor", "energy_j": 10.0,
        "tokens_out": 5, "duration_ms": 1000,
        "peak_temp_c": 50.0,
    }, 101.0)
    assert out.get("ok") is True
    from esg import _detail
    ev = [e for e in state.store.esg_events()
          if e["event_type"] == "job_completed"][-1]
    assert _detail(ev).get("scheduler_mode") == "thermal_aware"


def test_y1_jobs_result_rate_limited(tmp_path):
    state = _state(tmp_path)
    from rate_limit import DEFAULT_MAX
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")["token"]
    codes = []
    for _ in range(DEFAULT_MAX + 2):
        r = c.post("/jobs/result", headers=_auth(tok),
                   json={"job_id": "nope", "status": "ok",
                         "energy_source": "none"})
        codes.append(r.status_code)
    assert 429 in codes


def test_y1_admin_password_cannot_match_worker():
    room = Room(room_code="X")
    room.set_worker_password("same-password-xyz")
    try:
        room.set_admin_password("same-password-xyz")
        assert False, "expected ApiError"
    except ApiError as e:
        assert e.status == 400


def test_y2_tokens_estimated_excluded_from_tier1():
    events = [
        {"ts": 1, "node": "A", "event_type": "job_completed",
         "detail": {
             "status": "ok", "energy_source": "sensor",
             "energy_j": 100.0, "tokens_out": 50,
             "tokens_estimated": True,
             "scheduler_mode": "thermal_aware",
         }},
        {"ts": 2, "node": "A", "event_type": "job_completed",
         "detail": {
             "status": "ok", "energy_source": "sensor",
             "energy_j": 40.0, "tokens_out": 20,
             "tokens_estimated": False,
             "scheduler_mode": "thermal_aware",
         }},
    ]
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 1
    assert abs(r["tier1_measured"]["j_per_token"] - 2.0) < 1e-9


def test_y2_esg_csv_is_event_log(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    state.store.insert_esg_event(
        1.0, "A", "flagged",
        {"pred": 90, "threshold_at_time": 75.0, "predicted_max": 90})
    r = c.get("/api/esg.csv", headers=_auth(admin))
    assert r.status_code == 200
    assert "threshold_at_time" in r.text
    assert "flagged" in r.text
    assert "event," in r.text or r.text.startswith("ts,node,event")


def test_y2_threshold_changed_event(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    r = c.post("/api/settings", headers=_auth(admin),
               json={"threshold_c": 80})
    assert r.status_code == 200
    evs = [e for e in state.store.esg_events()
           if e["event_type"] == "threshold_changed"]
    assert len(evs) == 1
    from esg import _detail
    d = _detail(evs[0])
    assert d.get("new") == 80
    assert d.get("old") == 75.0
