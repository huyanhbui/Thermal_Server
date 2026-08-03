"""P1: barrier claim/result/host vs lifecycle — không dùng 409 ROOM_LIFECYCLE."""
from __future__ import annotations

import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from errors import ApiError
from server import (
    HOST_NODE,
    create_app,
    host_claim_once,
    make_state,
    _run_room_lifecycle,
)


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


def _queues_empty(state):
    assert state.balancer.pending() == []
    assert state.balancer.reserved() == []
    assert state.balancer.list_active() == []


def _reserve_chat(state, node, prompt):
    job = state.balancer.enqueue_job(
        job_type="chat", prompt=prompt,
        deadline_s=60, duration_s=0, cores=0)
    assert job is not None
    reserved = state.balancer.reserve(
        job["id"], node, until=time.time() + 30, now=time.time())
    assert reserved is not None
    return reserved


def _start_close_bg(state):
    """Start lifecycle close ở thread khác; chờ writer_waiting (không join).

    Gọi từ trong mutation_section: close chờ readers=0 → không deadlock
    nếu hook chỉ chờ writer_waiting rồi abort.
    """
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
    assert state.lifecycle.writer_waiting(), "close chưa vào write-wait"
    return t, done


def test_worker_claim_seam_during_close_rotate_reopen(tmp_path):
    """Sau drain: claim seam không lấy prompt (accepting=False / queue trống)."""
    for kind in ("close", "rotate", "reopen"):
        state, c = _boot(tmp_path / kind)
        admin = _join(c, state, role="admin", node="Adm",
                      password="admin-pass-ok12")
        _join(c, state, role="worker", node="W1",
              password="worker-pass-ok12")
        _reserve_chat(state, "W1", "PROMPT-BI-MAT")
        seam = {"claimed": "unset", "blocking": None}

        def after_drain():
            seam["blocking"] = state.lifecycle.is_blocking()
            # Không gọi TestClient lồng (deadlock). Seam = claim thật.
            seam["claimed"] = state.balancer.claim("W1", now=time.time())

        state.lifecycle._after_drain_hook = after_drain
        if kind == "close":
            assert c.post("/api/room/close",
                          headers=_auth(admin)).status_code == 200
        elif kind == "rotate":
            assert c.post("/api/room/bootstrap", headers=_auth(admin), json={
                "display_name": "R",
                "worker_password": "worker-pass-ok55",
                "admin_password": "admin-pass-ok55",
            }).status_code == 200
        else:
            assert c.post("/api/room/reopen-bootstrap").status_code == 200

        assert seam["blocking"] is True
        assert seam["claimed"] is None
        _queues_empty(state)


def test_worker_http_claim_waits_then_token_revoked(tmp_path):
    """Thread riêng: /jobs/next chờ gate rồi 401 TOKEN_REVOKED."""
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok12")
    _reserve_chat(state, "W1", "PROMPT-BI-MAT")
    started = threading.Event()
    result = {"status": None, "code": None}

    def after_drain():
        started.set()
        # Cho claim thread kịp vào wait_open
        time.sleep(0.15)

    def claimer():
        assert started.wait(timeout=5)
        r = c.get("/jobs/next?wait=5", headers=_auth(wtok))
        result["status"] = r.status_code
        try:
            body = r.json()
            result["code"] = (body.get("error") or {}).get("code")
        except Exception:
            result["code"] = None

    state.lifecycle._after_drain_hook = after_drain
    t = threading.Thread(target=claimer)
    t.start()
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    t.join(timeout=10)
    assert result["status"] == 401, result
    assert result["code"] == "TOKEN_REVOKED"
    _queues_empty(state)


def test_worker_claim_aborts_when_close_between_revalidate_and_claim(tmp_path):
    """Linearizable: seam trước claim kích close → 401, không claim."""
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok12")
    _reserve_chat(state, "W1", "PROMPT-CLAIM-RACE")
    close_t = {"t": None}

    def before_claim():
        close_t["t"], _ = _start_close_bg(state)

    state.lifecycle._before_claim_hook = before_claim
    r = c.get("/jobs/next?wait=2", headers=_auth(wtok))
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"
    assert state.balancer.list_active() == []
    if close_t["t"] is not None:
        close_t["t"].join(timeout=5)


def test_host_claim_skipped_during_lifecycle(tmp_path):
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    _reserve_chat(state, HOST_NODE, "HOST-PROMPT-CU")
    host_claim = {"job": "unset"}

    def after_drain():
        if state.lifecycle._before_host_claim_hook:
            state.lifecycle._before_host_claim_hook()
        # Giống host_claim_once: writer_waiting/blocking → abort
        try:
            state.lifecycle.ensure_commit_allowed()
            host_claim["job"] = state.balancer.claim(
                HOST_NODE, now=time.time())
        except ApiError:
            host_claim["job"] = None

    state.lifecycle._before_host_claim_hook = lambda: None
    state.lifecycle._after_drain_hook = after_drain
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    assert host_claim["job"] is None
    _queues_empty(state)


def test_host_claim_aborts_when_close_between_revalidate_and_claim(tmp_path):
    """host_claim_once: seam trước claim → TOKEN_REVOKED, không lấy job."""
    state, c = _boot(tmp_path)
    _join(c, state, role="admin", node="Adm",
          password="admin-pass-ok12")
    _reserve_chat(state, HOST_NODE, "HOST-RACE")
    close_t = {"t": None}

    def before_host():
        close_t["t"], _ = _start_close_bg(state)

    state.lifecycle._before_host_claim_hook = before_host
    err = None
    job = "unset"
    try:
        job = host_claim_once(state)
    except ApiError as e:
        err = e
    assert err is not None
    assert err.status == 401
    assert err.code == "TOKEN_REVOKED"
    assert job == "unset"
    assert state.balancer.list_active() == []
    if close_t["t"] is not None:
        close_t["t"].join(timeout=5)


def test_jobs_result_aborts_when_close_between_precheck_and_commit(tmp_path):
    """Result: alive precheck → close chen → 401, không ghi ESG/chat done."""
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok12")
    job = _reserve_chat(state, "W1", "P")
    claimed = state.balancer.claim("W1", now=time.time())
    assert claimed is not None
    state.chat.enqueue(claimed["id"], queue_position=1,
                       estimated_wait_s=1.0, now=time.time())
    state.chat.mark_running(claimed["id"], "W1", now=time.time())
    esg_before = len(state.store.esg_events())
    close_t = {"t": None}

    def before_commit():
        # Không gọi run() đồng bộ dưới read-lock (deadlock).
        close_t["t"], _ = _start_close_bg(state)

    state.lifecycle._before_result_commit_hook = before_commit
    r = c.post("/jobs/result", headers=_auth(wtok), json={
        "job_id": claimed["id"],
        "status": "ok",
        "text": "khong-duoc-ghi",
        "energy_source": "none",
        "tokens_out": 3,
        "duration_ms": 10,
    })
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"
    assert len(state.store.esg_events()) == esg_before
    info = state.chat.get(claimed["id"])
    assert info is None or info.get("text") != "khong-duoc-ghi"
    if close_t["t"] is not None:
        close_t["t"].join(timeout=5)


def test_jobs_result_aborts_when_close_after_complete_before_esg(tmp_path):
    """P1: close ngay sau balancer.complete → 401, không ESG/chat mutation."""
    state, c = _boot(tmp_path)
    _join(c, state, role="admin", node="Adm",
          password="admin-pass-ok12")
    wtok = _join(c, state, role="worker", node="W1",
                 password="worker-pass-ok12")
    job = _reserve_chat(state, "W1", "P-AFTER-COMPLETE")
    claimed = state.balancer.claim("W1", now=time.time())
    assert claimed is not None
    state.chat.enqueue(claimed["id"], queue_position=1,
                       estimated_wait_s=1.0, now=time.time())
    state.chat.mark_running(claimed["id"], "W1", now=time.time())
    esg_before = len(state.store.esg_events())
    close_t = {"t": None}

    def after_complete():
        close_t["t"], _ = _start_close_bg(state)

    state.lifecycle._after_complete_hook = after_complete
    r = c.post("/jobs/result", headers=_auth(wtok), json={
        "job_id": claimed["id"],
        "status": "ok",
        "text": "sau-complete-khong-ghi",
        "energy_source": "none",
        "tokens_out": 5,
        "duration_ms": 12,
    })
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"
    assert len(state.store.esg_events()) == esg_before
    info = state.chat.get(claimed["id"])
    assert info is None or info.get("text") != "sau-complete-khong-ghi"
    if close_t["t"] is not None:
        close_t["t"].join(timeout=5)


def test_chat_after_drain_uses_token_revoked_not_room_lifecycle(tmp_path):
    """Sau drain trên runner thread: require_open → 401 (không TestClient lồng)."""
    state, c = _boot(tmp_path)
    admin = _join(c, state, role="admin", node="Adm",
                  password="admin-pass-ok12")
    # AuthContext từ resolve
    auth = state.room.resolve(admin)
    out = {"err": None}

    def after_drain():
        try:
            state.lifecycle.require_open_and_alive(
                state.room, auth, now=time.time())
            out["err"] = "no-raise"
        except Exception as e:
            out["err"] = e

    state.lifecycle._after_drain_hook = after_drain
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    assert isinstance(out["err"], ApiError)
    assert out["err"].status == 401
    assert out["err"].code == "TOKEN_REVOKED"
