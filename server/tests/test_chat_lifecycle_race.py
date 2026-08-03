"""P1: race /chat chen giữa drain_all và lifecycle finish.

Barrier/seam sau drain: không commit job; sau close/rotate/reopen queue trống.
Dùng 401 TOKEN_REVOKED (docs/03) — không 409 ROOM_LIFECYCLE.
"""
from __future__ import annotations

import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from errors import ApiError
from server import create_app, make_state


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _boot(tmp_path, *, name="A"):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    r = c.post("/api/room/bootstrap", json={
        "display_name": name,
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    assert r.status_code == 200, r.text
    return state, c


def _admin_token(c, state):
    r = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "admin-pass-ok12",
        "role": "admin",
        "node_name": "HostAdmin",
        "capabilities": CAPS,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def _queues_empty(state):
    assert state.balancer.pending() == []
    assert state.balancer.reserved() == []
    assert state.balancer.list_active() == []
    assert state.chat.counts() == {"chat_pending": 0, "chat_running": 0}


def _race_chat_during_lifecycle(tmp_path, *, trigger, after_passwords=None):
    """Seam sau drain: require_open_and_alive → 401; queue trống; worker mới sạch."""
    state, c = _boot(tmp_path)
    admin = _admin_token(c, state)
    auth = state.room.resolve(admin)
    chat_err = {"exc": None}

    def after_drain():
        try:
            state.lifecycle.require_open_and_alive(
                state.room, auth, now=time.time())
            # Nếu lọt qua — thử enqueue (phải fail vì accepting=False)
            job = state.balancer.enqueue_job(
                job_type="chat", prompt="PROMPT-CU-KHONG-DUOC-RO")
            chat_err["exc"] = ("enqueued", job)
        except Exception as e:
            chat_err["exc"] = e

    state.lifecycle._after_drain_hook = after_drain
    trigger(state, c, admin)

    assert isinstance(chat_err["exc"], ApiError), chat_err
    assert chat_err["exc"].status == 401
    assert chat_err["exc"].code == "TOKEN_REVOKED"
    _queues_empty(state)

    wp, ap = after_passwords or ("worker-pass-ok99", "admin-pass-ok99")
    if not state.room.has_password():
        r = c.post("/api/room/bootstrap", json={
            "display_name": "PhongMoi",
            "worker_password": wp,
            "admin_password": ap,
        })
        assert r.status_code == 200, r.text
    wr = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": wp,
        "role": "worker",
        "node_name": "Node-Phong-Moi",
        "capabilities": CAPS,
    })
    assert wr.status_code in (200, 201), wr.text
    wtok = wr.json()["token"]
    for _ in range(5):
        nj = c.get("/jobs/next?wait=0", headers=_auth(wtok))
        assert nj.status_code in (200, 204)
        if nj.status_code == 200:
            job = nj.json()
            assert job.get("type") != "chat"
            assert "PROMPT-CU" not in str(job.get("prompt") or "")
    _queues_empty(state)


def test_chat_race_blocked_during_room_close(tmp_path):
    def trigger(state, c, admin):
        r = c.post("/api/room/close", headers=_auth(admin))
        assert r.status_code == 200, r.text

    _race_chat_during_lifecycle(tmp_path, trigger=trigger)


def test_chat_race_blocked_during_password_rotate(tmp_path):
    def trigger(state, c, admin):
        r = c.post("/api/room/bootstrap", headers=_auth(admin), json={
            "display_name": "Rotated",
            "worker_password": "worker-pass-ok55",
            "admin_password": "admin-pass-ok55",
        })
        assert r.status_code == 200, r.text

    _race_chat_during_lifecycle(
        tmp_path, trigger=trigger,
        after_passwords=("worker-pass-ok55", "admin-pass-ok55"))


def test_chat_race_blocked_during_reopen_bootstrap(tmp_path):
    def trigger(state, c, admin):
        r = c.post("/api/room/reopen-bootstrap")
        assert r.status_code == 200, r.text

    _race_chat_during_lifecycle(tmp_path, trigger=trigger)


def test_chat_http_waits_gate_then_401(tmp_path):
    state, c = _boot(tmp_path)
    admin = _admin_token(c, state)
    started = threading.Event()
    out = {"status": None, "code": None}

    def after_drain():
        started.set()
        time.sleep(0.15)

    def chatter():
        assert started.wait(timeout=5)
        r = c.post("/chat", headers=_auth(admin),
                   json={"prompt": "PROMPT-CU"})
        out["status"] = r.status_code
        out["code"] = r.json()["error"]["code"]

    state.lifecycle._after_drain_hook = after_drain
    t = threading.Thread(target=chatter)
    t.start()
    assert c.post("/api/room/close", headers=_auth(admin)).status_code == 200
    t.join(timeout=10)
    assert out["status"] == 401, out
    assert out["code"] == "TOKEN_REVOKED"
    _queues_empty(state)
