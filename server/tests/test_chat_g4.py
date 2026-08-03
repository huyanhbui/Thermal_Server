"""Chat queue chỉ dùng worker READY thật, X2/X3 trên đường phân tán."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

import time
from fastapi.testclient import TestClient

from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, apply_job_result, create_app,
                    make_state, run_forecast_cycle, run_scheduler_cycle)


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
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_ready(state, name, now=100.0, temp=45.0):
    for i in range(10):
        state.store.insert(name, now - 90 + i * 10, temp, None, 10.0, 20.0)
    run_forecast_cycle(state, now)
    # Chat scheduling requires the agent to have proved it is running the
    # selected catalog artifact; telemetry alone is deliberately insufficient.
    from room_assets import RUNTIME_ID, get_model
    model = get_model(state.settings.get()["model_id"])
    state.forecast_cache.patch(
        name, model_ready=True, model_id=model["model_id"],
        model_sha256=model["sha256"], model_generation=state.llm_generation,
        runtime_id=RUNTIME_ID)


def test_post_chat_returns_202_immediately(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    _join(c, "Node-A")
    _seed_ready(state, "Node-A")
    r = c.post("/chat", headers=_auth(admin),
               json={"prompt": "Xin chào", "max_tokens": 64})
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and body["queue_position"] >= 1
    assert body["estimated_wait_s"] >= 0
    g = c.get(f"/chat/{body['job_id']}", headers=_auth(admin))
    assert g.status_code == 200
    assert g.json()["status"] == "queued"


def test_worker_cannot_post_chat(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")["token"]
    r = c.post("/chat", headers=_auth(tok), json={"prompt": "hi"})
    assert r.status_code == 403


def test_flagged_node_does_not_receive_chat(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-Hot")["token"]
    _seed_ready(state, "Node-Hot", now=100.0, temp=90.0)
    # Force AT_RISK + flag
    state.balancer.set_flag("Node-Hot", True)
    state.forecast_cache.patch("Node-Hot", state="AT_RISK",
                               predicted_max_c=95.0, current_temp_c=90.0,
                               effective_threshold_c=75.0,
                               last_sample_ts=100.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "test flag"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NO_LLM_READY"


def test_chat_rejects_when_no_worker_has_proved_ready_model(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]

    r = c.post("/chat", headers=_auth(admin), json={"prompt": "P2 please"})

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NO_LLM_READY"


def test_x3_late_chat_result_ignored_no_double_inflight(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "late"})
    jid = r.json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    claimed = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert claimed.status_code == 200
    assert claimed.json()["type"] == "chat"
    # Simulate reservation expiry path: cancel active then late result
    state.balancer.cancel_active("Node-A")
    state.forecast_cache.adjust_inflight("Node-A", -1)
    before = state.forecast_cache.get("Node-A").inflight
    out = c.post("/jobs/result", headers=_auth(tok),
                 json={"job_id": jid, "status": "ok", "text": "too late",
                       "tokens_out": 3, "energy_source": "none"})
    assert out.status_code == 200
    assert out.json().get("ignored") is True
    assert state.forecast_cache.get("Node-A").inflight == before


def test_x2_chat_reassigns_from_expired_worker_to_another_ready_worker(tmp_path):
    """Lease hết hạn phải chọn worker READY khác, không rơi về pseudo-host."""
    from scheduler import reap_expired

    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    _join(c, "Node-A")
    _join(c, "Node-B")
    _seed_ready(state, "Node-A", now=100.0)
    _seed_ready(state, "Node-B", now=100.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "survive X2"})
    jid = r.json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    reserved = [j for j in state.balancer.reserved() if j["id"] == jid]
    assert reserved and reserved[0]["target"] == "Node-A"

    cache = state.forecast_cache.all()
    reap_expired(cache, state.balancer, 121.0)
    state.forecast_cache.adjust_inflight("Node-A", -1)
    state.forecast_cache.set_recently_failed_until(
        "Node-A", cache["Node-A"].recently_failed_until)
    state.forecast_cache.patch("Node-A", state="STALE")
    state.forecast_cache.patch("Node-B", state="READY", last_sample_ts=130.0)
    run_scheduler_cycle(state, 130.0)

    reserved2 = [j for j in state.balancer.reserved() if j["id"] == jid]
    assert reserved2 and reserved2[0]["target"] == "Node-B", reserved2


def test_join_room_config_has_adr005_pins(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    data = _join(c, "Node-A")
    cfg = data["room_config"]
    assert cfg["model_id"] == "qwen2.5-0.5b-instruct-q4_k_m"
    assert cfg["model_filename"] == "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
    assert cfg["runtime_sha256"].startswith("CA78DF")
    assert cfg["model_sha256"].startswith("6EB923")
    assert "huggingface.co" in cfg["model_url"]
    assert "allowed_domains" in cfg


def test_kick_running_chat_requeues_not_stuck_running(tmp_path):
    """Kick khi chat đang chạy → tracker queued (không kẹt running)."""
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "kick me"})
    jid = r.json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    assert c.get("/jobs/next?wait=0", headers=_auth(tok)).status_code == 200
    assert state.chat.get(jid)["status"] == "running"
    kr = c.post("/api/nodes/Node-A/kick", headers=_auth(admin))
    assert kr.status_code == 200
    g = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g["status"] == "queued", g
    assert any(j["id"] == jid for j in state.balancer.pending())


def test_runtime_ready_false_blocks_chat_not_burn(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    c.post("/nodes/ready", headers=_auth(tok),
           json={"runtime_ready": False, "model_id": "x"})
    assert state.forecast_cache.get("Node-A").model_ready is False
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "no llm"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NO_LLM_READY"
    # Burn vẫn nhận được khi model_ready=false
    state.balancer.enqueue_job(job_type="burn", duration_s=5)
    state.forecast_cache.patch("Node-A", state="READY", model_ready=False,
                               last_sample_ts=101.0)
    run_scheduler_cycle(state, 102.0)
    burn_claim = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert burn_claim.status_code == 200
    assert burn_claim.json().get("type", "burn") == "burn"


def test_energy_source_model_requires_energy_j(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    state.balancer.enqueue_job()
    run_scheduler_cycle(state, 100.0)
    job = c.get("/jobs/next?wait=0", headers=_auth(tok)).json()
    r = c.post("/jobs/result", headers=_auth(tok),
               json={"job_id": job["id"], "status": "ok",
                     "energy_source": "model"})
    assert r.status_code == 422


def test_burn_not_assigned_to_host(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    _join(c, "Node-A")
    # No ready candidates
    state.balancer.enqueue_job(job_type="burn", duration_s=5)
    run_scheduler_cycle(state, 50.0)
    assert not state.balancer.reserved()
    assert any(j.get("target") is None for j in state.balancer.pending())


def test_predicted_max_equals_current_plus_delta_t(tmp_path):
    """Bất biến 6: số gắn cờ = current + ΔT hiển thị."""
    state = _state(tmp_path)
    _seed_ready(state, "Node-A", now=100.0, temp=50.0)
    fc = state.forecast_cache.get("Node-A")
    assert fc is not None
    assert fc.delta_t_c is not None
    assert fc.current_temp_c is not None
    assert fc.predicted_max_c is not None
    assert abs(fc.predicted_max_c - (fc.current_temp_c + fc.delta_t_c)) < 1e-6


def test_worker_chat_error_retries_when_attempts_remain(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    _join(c, "Node-A")
    _seed_ready(state, "Node-A", now=50.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "worker fail"})
    jid = r.json()["job_id"]
    run_scheduler_cycle(state, 50.0)
    job = state.balancer.claim("Node-A", now=50.0)
    assert job is not None and job["id"] == jid
    out = apply_job_result(state, "Node-A", {
        "job_id": jid, "status": "error",
        "error_message": "worker failed", "energy_source": "none",
    }, 51.0)
    assert out.get("retried") is True
    g = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g["status"] == "queued"


def test_x10_timeout_retries_then_errors_after_max_attempts(tmp_path):
    """Timeout lần đầu → requeue; attempts đã MAX → error + phạt node."""
    from scheduler import MAX_ATTEMPTS

    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    tok = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A", now=100.0)
    r = c.post("/chat", headers=_auth(admin), json={"prompt": "hang"})
    jid = r.json()["job_id"]
    run_scheduler_cycle(state, 100.0)
    claimed = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert claimed.status_code == 200
    out = c.post("/jobs/result", headers=_auth(tok),
                 json={"job_id": jid, "status": "timeout",
                       "error_message": "llm job deadline exceeded",
                       "energy_source": "none",
                       "attempt_id": claimed.json()["attempt_id"]})
    assert out.status_code == 200
    assert out.json().get("retried") is True
    g = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g["status"] == "queued"
    assert state.forecast_cache.get("Node-A").consecutive_errors >= 1

    # Giữ telemetry tươi (STALE_AFTER_S=10) rồi ép attempts = MAX
    now2 = 105.0
    state.forecast_cache.patch("Node-A", state="READY", last_sample_ts=now2)
    run_scheduler_cycle(state, now2)
    with state.balancer._lock:
        for j in state.balancer._queue:
            if j["id"] == jid:
                j["attempts"] = MAX_ATTEMPTS
                break
    claimed = c.get("/jobs/next?wait=0", headers=_auth(tok))
    assert claimed.status_code == 200
    out2 = c.post("/jobs/result", headers=_auth(tok),
                  json={"job_id": jid, "status": "timeout",
                        "error_message": "llm job deadline exceeded",
                        "energy_source": "none",
                        "attempt_id": claimed.json()["attempt_id"]})
    assert out2.status_code == 200
    assert out2.json().get("retried") is not True
    g2 = c.get(f"/chat/{jid}", headers=_auth(admin)).json()
    assert g2["status"] == "error"
