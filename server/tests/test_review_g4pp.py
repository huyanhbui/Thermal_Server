"""Nợ review G4++: ΔT né−chọn, lease MAX, password 2 chiều, host tokens, tier3 tách."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"
os.environ["POC_HOST_LLM_STUB"] = "1"

from fastapi.testclient import TestClient

from balancer import BURN_LEASE_GRACE_S, LoadBalancer
from errors import ApiError
from esg import TIER3_LABEL, compute_report
from forecast_cache import ForecastCache, NodeForecast
from llm import HostLlm
from room import Room
from scheduler import MAX_ATTEMPTS, schedule_once
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, apply_job_result, create_app,
                    make_state, run_forecast_cycle, run_scheduler_cycle)


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


def _nf(node, temp, *, now=100.0):
    return NodeForecast(
        node=node, state="READY",
        current_temp_c=temp, predicted_max_c=temp + 2.0,
        delta_t_c=2.0, idle_baseline_c=35.0,
        effective_threshold_c=75.0, p_idle_w=15.0, p_max_w=65.0,
        last_sample_ts=now, computed_at=now, model_ready=True,
    )


def test_d1_delta_t_via_apply_job_result(tmp_path):
    state = _state(tmp_path)
    cache = state.forecast_cache
    cache.put(_nf("Cool", 40.0))
    cache.put(_nf("Hot", 55.0))
    job = state.balancer.enqueue_job(
        job_type="chat", duration_s=0, cores=0, prompt="x", deadline_s=60)
    schedule_once(cache, state.balancer,
                  {"cool": 0.4, "idle": 0.25, "power": 0.15, "load": 0.2},
                  100.0, mode="thermal_aware")
    target = state.balancer.reserved()[0]["target"]
    claimed = state.balancer.claim(target, now=100.0)
    apply_job_result(state, target, {
        "job_id": claimed["id"], "status": "ok", "text": "ok",
        "energy_source": "sensor", "energy_j": 10.0, "tokens_out": 5,
        "peak_temp_c": 90.0, "duration_ms": 3_600_000.0,
    }, 101.0)
    from esg import _detail
    ev = [e for e in state.store.esg_events()
          if e["event_type"] == "job_completed"][-1]
    d = _detail(ev)
    assert abs(d["delta_t_avoided_c"] - 15.0) < 1e-9  # 55-40, không 90-40
    assert d.get("avoided_temp_c") == 55.0


def test_d1_single_candidate_no_delta_t(tmp_path):
    state = _state(tmp_path)
    state.forecast_cache.put(_nf("Solo", 42.0))
    state.balancer.enqueue_job(
        job_type="chat", duration_s=0, cores=0, prompt="x", deadline_s=60)
    schedule_once(state.forecast_cache, state.balancer,
                  {"cool": 0.4, "idle": 0.25, "power": 0.15, "load": 0.2},
                  100.0)
    target = state.balancer.reserved()[0]["target"]
    claimed = state.balancer.claim(target, now=100.0)
    apply_job_result(state, target, {
        "job_id": claimed["id"], "status": "ok",
        "energy_source": "none", "peak_temp_c": 80.0,
        "duration_ms": 1000.0,
    }, 101.0)
    from esg import _detail
    d = _detail([e for e in state.store.esg_events()
                 if e["event_type"] == "job_completed"][-1])
    assert d.get("delta_t_avoided_c") is None
    assert d.get("avoided_temp_c") is None


def test_d2_lease_at_max_attempts_fails_not_requeue(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    _join(c, "Node-A")
    for i in range(10):
        state.store.insert("Node-A", 100.0 - 90 + i * 10, 45.0, None, 10.0, 20.0)
    run_forecast_cycle(state, 100.0)
    from room_assets import RUNTIME_ID, get_model
    model = get_model(state.settings.get()["model_id"])
    state.forecast_cache.patch(
        "Node-A", model_ready=True, model_id=model["model_id"],
        model_sha256=model["sha256"], model_generation=state.llm_generation,
        runtime_id=RUNTIME_ID)
    jid = c.post("/chat", headers=_auth(admin),
                 json={"prompt": "lease-max"}).json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    claimed = state.balancer.claim("Node-A", now=100.0)
    assert claimed is not None
    with state.balancer._lock:
        state.balancer._active["Node-A"]["attempts"] = MAX_ATTEMPTS
        state.balancer._active["Node-A"]["active_deadline"] = 100.0 + 60
    state.chat.mark_running(jid, "Node-A", now=100.0)
    run_scheduler_cycle(state, 100.0 + 61.0)
    g = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g["status"] == "error"


def test_d3_worker_password_cannot_match_admin():
    room = Room(room_code="X")
    room.set_admin_password("admin-pass-ok")
    try:
        room.set_worker_password("admin-pass-ok")
        assert False
    except ApiError as e:
        assert e.status == 400


def test_y1_set_password_requires_allow_shared():
    room = Room(room_code="X")
    try:
        room.set_password("shared-password-x")
        assert False
    except ApiError as e:
        assert e.status == 400
    room.set_password("shared-password-x", allow_shared=True)
    assert room.has_password()


def test_d4_host_stub_tokens_estimated():
    llm = HostLlm(stub=True)
    reply = llm.generate("xin chào", {"max_tokens": 16})
    assert reply.tokens_estimated is True
    assert reply.tokens_out is None


def test_d5_tier3_split_no_single_kwh_projected():
    events = [
        {"ts": 0.0, "node": "A", "event_type": "job_completed",
         "detail": {
             "status": "ok", "energy_source": "sensor",
             "energy_j": 3_600_000.0, "tokens_out": 100,
             "scheduler_mode": "thermal_aware",
             "delta_t_avoided_c": 5.0, "duration_h": 1.0,
         }},
        {"ts": 3600.0, "node": "A", "event_type": "job_completed",
         "detail": {
             "status": "ok", "energy_source": "sensor",
             "energy_j": 0.0, "tokens_out": 1,
             "scheduler_mode": "thermal_aware",
         }},
    ]
    r = compute_report(events, {"leakage_w_per_c": 0.18})
    t3 = r["tier3_projected"]
    assert "kwh_projected" not in t3
    assert t3["kwh_projected_measured"] > 0
    assert t3["kwh_projected_derived"] > 0
    assert t3["kwh_projected_measured"] != t3["kwh_projected_derived"]
    assert TIER3_LABEL in t3["label_derived"]


def test_y3_burn_lease_includes_grace():
    q = LoadBalancer()
    q.enqueue_job(duration_s=10, cores=1)
    # reserve manually
    jid = q.pending()[0]["id"]
    q.reserve(jid, "N", until=1000.0, now=0.0)
    claimed = q.claim("N", now=0.0)
    assert claimed["active_deadline"] == 10.0 + BURN_LEASE_GRACE_S


def test_r1_rereserve_single_clears_avoided_temp(tmp_path):
    """Re-reserve chỉ còn 1 node → xóa avoided_temp_c cũ."""
    state = _state(tmp_path)
    w = {"cool": 0.4, "idle": 0.25, "power": 0.15, "load": 0.2}
    state.forecast_cache.put(_nf("Cool", 40.0))
    state.forecast_cache.put(_nf("Hot", 55.0))
    job = state.balancer.enqueue_job(
        job_type="chat", duration_s=0, cores=0, prompt="x", deadline_s=60)
    jid = job["id"]
    schedule_once(state.forecast_cache, state.balancer, w, 100.0)
    r0 = state.balancer.reserved()[0]
    assert r0.get("avoided_temp_c") == 55.0
    assert r0.get("assign_temp_c") == 40.0
    # Trả về pending (stamp cũ còn trên dict tới khi reserve lại)
    winner = r0["target"]
    assert state.balancer.requeue_front(jid) is not None
    # requeue_front không hạ inflight — trả chỗ để Cool nhận lại
    state.forecast_cache.adjust_inflight(winner, -1)
    # Loại Hot khỏi ứng viên
    state.forecast_cache.put(NodeForecast(
        node="Hot", state="STALE", current_temp_c=55.0,
        predicted_max_c=None, last_sample_ts=0.0, model_ready=True,
        idle_baseline_c=35.0, effective_threshold_c=75.0,
    ))
    schedule_once(state.forecast_cache, state.balancer, w, 100.0)
    r1 = state.balancer.reserved()
    assert len(r1) == 1
    assert r1[0]["target"] == "Cool"
    assert r1[0].get("avoided_temp_c") is None
    assert r1[0].get("assign_temp_c") == 40.0


def test_r2_assign_to_host_clears_thermal_stamps(tmp_path):
    state = _state(tmp_path)
    job = state.balancer.enqueue_job(
        job_type="chat", duration_s=0, cores=0, prompt="host", deadline_s=60)
    jid = job["id"]
    # Giả stamp từ lần reserve worker trước
    with state.balancer._lock:
        for j in state.balancer._queue:
            if j["id"] == jid:
                j["assign_temp_c"] = 40.0
                j["avoided_temp_c"] = 55.0
                j["assign_predicted_max_c"] = 42.0
                break
    out = state.balancer.assign_to_host(job, now=50.0, scheduler_mode="thermal_aware")
    assert out is not None
    assert out["target"] == "__host__"
    assert out.get("assign_temp_c") is None
    assert out.get("avoided_temp_c") is None
    assert out.get("assign_predicted_max_c") is None
    claimed = state.balancer.claim("__host__", now=50.0)
    apply_job_result(state, "__host__", {
        "job_id": jid, "status": "ok", "text": "ok",
        "energy_source": "none", "peak_temp_c": 90.0,
        "duration_ms": 1000.0,
    }, 51.0)
    from esg import _detail
    d = _detail([e for e in state.store.esg_events()
                 if e["event_type"] == "job_completed"][-1])
    assert d.get("delta_t_avoided_c") is None


def test_y1_stale_releases_reservation(tmp_path):
    from server import STALE_AFTER_S
    state = _state(tmp_path)
    # Telemetry tươi rồi nhảy quá STALE_AFTER_S
    for i in range(10):
        state.store.insert("Node-A", 100.0 - 90 + i * 10, 45.0, None, 10.0, 20.0)
    run_forecast_cycle(state, 100.0)
    assert state.forecast_cache.get("Node-A").state != "STALE"
    job = state.balancer.enqueue_job(
        job_type="chat", duration_s=0, cores=0, prompt="stale", deadline_s=60)
    jid = job["id"]
    state.balancer.reserve(
        jid, "Node-A", until=100.0 + 20.0, now=100.0,
        scheduler_mode="thermal_aware",
        assign_temp_c=45.0, avoided_temp_c=60.0)
    state.forecast_cache.adjust_inflight("Node-A", 1)
    assert state.balancer.reserved()
    assert state.forecast_cache.get("Node-A").inflight == 1
    stale_now = 100.0 + STALE_AFTER_S + 1.0
    run_forecast_cycle(state, stale_now)
    assert state.forecast_cache.get("Node-A").state == "STALE"
    assert state.balancer.reserved() == []
    pending_ids = [j["id"] for j in state.balancer.pending()]
    assert jid in pending_ids
    assert state.forecast_cache.get("Node-A").inflight == 0
