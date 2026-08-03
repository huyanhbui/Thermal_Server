"""P1: lifecycle atomic + WS/long-poll revalidate khi đóng/đổi phòng."""
from __future__ import annotations

import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from room import Room, make_default_room
from server import create_app, make_state


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_join_barrier_cannot_keep_token_across_lifecycle_close():
    """Join chen giữa validate và phát token — lifecycle_close thắng."""
    room = make_default_room()
    barrier = threading.Barrier(2)
    results = {"join_err": None, "token": None}

    def mid():
        barrier.wait(timeout=5)
        # Đóng phòng atomic trong lúc join đã validate xong
        room.lifecycle_close(now=time.time())
        barrier.wait(timeout=5)

    room._join_mid_hook = mid

    def do_join():
        try:
            tok, _ = room.join(
                room_code=room.room_code,
                password="local-dev-password",
                node_name="Race-Node",
                role="worker", ip="127.0.0.1")
            results["token"] = tok
        except Exception as e:
            results["join_err"] = e

    t = threading.Thread(target=do_join)
    t.start()
    barrier.wait(timeout=5)
    barrier.wait(timeout=5)
    t.join(timeout=5)
    assert results["token"] is None
    assert results["join_err"] is not None
    # Sau close không còn password → join mới cũng fail
    try:
        room.resolve(results["token"]) if results["token"] else None
    except Exception:
        pass
    assert room.generation >= 1
    assert not room.has_password()


def test_password_rotate_atomic_old_password_join_fails(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    c.post("/api/room/bootstrap", json={
        "display_name": "A",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    join_result = {}

    def mid():
        # Đang nhả lock của join — rotate atomic chen vào
        now = time.time()
        from server import _run_room_lifecycle
        _run_room_lifecycle(
            state, reason="password_rotate", now=now,
            finish_fn=lambda: state.room.lifecycle_rotate_passwords(
                "worker-pass-ok99", "admin-pass-ok99", now=now))

    state.room._join_mid_hook = mid

    def sneaky_join():
        try:
            r = c.post("/join", json={
                "room_code": code,
                "password": "worker-pass-ok12",
                "role": "worker",
                "node_name": "Sneaky",
                "capabilities": CAPS,
            })
            join_result["status"] = r.status_code
            if r.status_code == 201:
                join_result["token"] = r.json()["token"]
        except Exception as e:
            join_result["exc"] = str(e)

    t = threading.Thread(target=sneaky_join)
    t.start()
    t.join(timeout=15)
    state.room._join_mid_hook = None
    assert join_result.get("status") == 401
    tok = join_result.get("token")
    if tok:
        assert c.get("/api/state", headers=_auth(tok)).status_code in (401, 403)
    bad = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "After",
        "capabilities": CAPS,
    })
    assert bad.status_code == 401
    # Password mới vẫn join được
    ok = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "worker-pass-ok99",
        "role": "worker",
        "node_name": "NewNode",
        "capabilities": CAPS,
    })
    assert ok.status_code == 201


def test_long_poll_aborts_on_room_close(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "r.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    c.post("/api/room/bootstrap", json={
        "display_name": "P",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    admin = c.post("/join", json={
        "room_code": code, "password": "admin-pass-ok12", "role": "admin",
    }).json()["token"]
    wtok = c.post("/join", json={
        "room_code": code, "password": "worker-pass-ok12",
        "role": "worker", "node_name": "Poller", "capabilities": CAPS,
    }).json()["token"]

    poll_status = {}

    def poll():
        r = c.get("/jobs/next?wait=5", headers=_auth(wtok))
        poll_status["code"] = r.status_code
        try:
            poll_status["body"] = r.json()
        except Exception:
            poll_status["body"] = None

    t = threading.Thread(target=poll)
    t.start()
    time.sleep(0.15)
    c.post("/api/room/close", headers=_auth(admin))
    t.join(timeout=10)
    assert poll_status.get("code") == 401
    # Slot poll đã clear — node cùng tên phòng mới không bị 429 vì key cũ
    assert state._job_polls == set() or wtok not in str(state._job_polls)


def test_ws_closes_when_room_closed(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "r.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    c.post("/api/room/bootstrap", json={
        "display_name": "P",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    admin = c.post("/join", json={
        "room_code": code, "password": "admin-pass-ok12", "role": "admin",
    }).json()["token"]
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": admin})
        _ = ws.receive_json()
        c.post("/api/room/close", headers=_auth(admin))
        # Đợi vòng push kế tiếp phát hiện token chết
        closed = False
        try:
            for _ in range(5):
                ws.receive_json()
        except Exception:
            closed = True
        assert closed


def test_stale_node_kept_in_payload_after_active_window(tmp_path):
    from forecast_cache import NodeForecast
    from server import ACTIVE_WINDOW_S, build_state_payload

    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    now = 1_000_000.0
    old = now - ACTIVE_WINDOW_S - 60
    state.store.insert("Ghost", old, 50.0, None, 10.0, 20.0)
    state.forecast_cache.put(NodeForecast(
        node="Ghost", state="STALE", last_sample_ts=old,
        computed_at=old, reason="no fresh telemetry"))
    payload = build_state_payload(state, now)
    names = [n["name"] for n in payload["nodes"]]
    assert "Ghost" in names
    ghost = next(n for n in payload["nodes"] if n["name"] == "Ghost")
    assert ghost["stale"] is True
    assert ghost["live"] is False
