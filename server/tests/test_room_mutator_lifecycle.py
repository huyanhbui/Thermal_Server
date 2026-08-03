"""P1: leave/ingest/admin mutators revalidate trong lifecycle read-lock."""
from __future__ import annotations

import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state, _run_room_lifecycle


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _ready_body(state):
    from room_assets import RUNTIME_ID, get_model
    model = get_model(state.settings.get()["model_id"])
    return {
        "runtime_ready": True,
        "model_id": model["model_id"],
        "model_sha256": model["sha256"],
        "model_generation": state.llm_generation,
        "runtime_id": RUNTIME_ID,
    }


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
    return state, c


def _join(c, state, *, role, node, password):
    r = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": password,
        "role": role,
        "node_name": node,
        "capabilities": CAPS,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def _start_close_bg(state):
    done = threading.Event()

    def closer():
        now = time.time()
        _run_room_lifecycle(
            state, reason="close", now=now,
            finish_fn=lambda: state.room.lifecycle_close(
                now=now, ip="testclient"))
        done.set()

    t = threading.Thread(target=closer, daemon=True)
    t.start()
    deadline = time.time() + 5.0
    while not state.lifecycle.writer_waiting() and time.time() < deadline:
        time.sleep(0.005)
    assert state.lifecycle.writer_waiting()
    return t, done


def test_old_leave_cannot_release_work_after_close_reopen(tmp_path):
    """Auth cũ pass → close/reopen worker mới cùng tên → leave cũ 401, job mới sống."""
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    old_tok = _join(c, state, role="worker", node="W1",
                    password="worker-pass-ok12")

    # Close + bootstrap lại + worker mới cùng node
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    assert c.post("/api/room/bootstrap", json={
        "display_name": "B",
        "worker_password": "worker-pass-ok99",
        "admin_password": "admin-pass-ok99",
    }).status_code == 200
    new_tok = _join(c, state, role="worker", node="W1",
                    password="worker-pass-ok99")
    job = state.balancer.enqueue_job(
        job_type="chat", prompt="KEEP-ME",
        deadline_s=60, duration_s=0, cores=0)
    assert job is not None
    reserved = state.balancer.reserve(
        job["id"], "W1", until=time.time() + 30, now=time.time())
    assert reserved is not None
    claimed = state.balancer.claim("W1", now=time.time())
    assert claimed is not None
    jid = claimed["id"]

    r = c.post("/leave", headers=_auth(old_tok))
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"
    # Job room mới không bị hủy/requeue bởi leave token cũ
    active = state.balancer.list_active()
    assert any(j.get("id") == jid for _, j in active), active
    # Token mới vẫn sống
    r2 = c.post("/nodes/ready", headers=_auth(new_tok),
                json=_ready_body(state))
    assert r2.status_code == 200, r2.text


def test_old_ingest_blocked_after_close_reopen(tmp_path):
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    old_tok = _join(c, state, role="worker", node="W1",
                    password="worker-pass-ok12")
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    assert c.post("/api/room/bootstrap", json={
        "display_name": "B",
        "worker_password": "worker-pass-ok99",
        "admin_password": "admin-pass-ok99",
    }).status_code == 200
    _join(c, state, role="worker", node="W1",
          password="worker-pass-ok99")
    before = state.store.latest("W1")
    r = c.post("/ingest", headers=_auth(old_tok), json={
        "cpu_temp": 99.0, "cpu_util": 50.0, "power_source": "none",
    })
    assert r.status_code == 401, r.text
    after = state.store.latest("W1")
    assert after == before


def test_old_admin_kick_blocked_after_close_reopen(tmp_path):
    state, c = _boot(tmp_path)
    old_admin = _join(c, state, role="admin", node="Adm",
                      password="admin-pass-ok12")
    assert c.post("/api/room/close", headers=_auth(old_admin)).status_code == 200
    assert c.post("/api/room/bootstrap", json={
        "display_name": "B",
        "worker_password": "worker-pass-ok99",
        "admin_password": "admin-pass-ok99",
    }).status_code == 200
    new_admin = _join(c, state, role="admin", node="Adm2",
                      password="admin-pass-ok99")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok99")
    r = c.post("/api/nodes/W1/kick", headers=_auth(old_admin))
    assert r.status_code == 401, r.text
    # Worker mới vẫn sẵn sàng
    r2 = c.post("/nodes/ready", headers=_auth(wtok),
                json=_ready_body(state))
    assert r2.status_code == 200
    # Admin mới vẫn kick được
    r3 = c.post("/api/nodes/W1/kick", headers=_auth(new_admin))
    assert r3.status_code == 200, r3.text


def test_leave_aborts_when_close_between_auth_and_mutation(tmp_path):
    """Barrier: seam trước release → close → 401, không side effect."""
    state, c = _boot(tmp_path)
    _join(c, state, role="admin", node="Adm",
          password="admin-pass-ok12")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok12")
    job = state.balancer.enqueue_job(
        job_type="burn", duration_s=5, cores=1)
    state.balancer.reserve(
        job["id"], "W1", until=time.time() + 30, now=time.time())
    claimed = state.balancer.claim("W1", now=time.time())
    assert claimed is not None
    close_t = {"t": None}

    def before_leave_mut():
        close_t["t"], _ = _start_close_bg(state)

    state.lifecycle._before_room_mut_hook = before_leave_mut
    r = c.post("/leave", headers=_auth(wtok))
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"
    if close_t["t"] is not None:
        close_t["t"].join(timeout=5)
