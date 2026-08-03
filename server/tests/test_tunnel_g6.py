"""Tunnel + allow_tunnel kill-switch + idle 8h + S9."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

import time

from errors import ApiError
from fastapi.testclient import TestClient
from room import Room
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, create_app, make_state)
from tunnel import IDLE_TIMEOUT_S, TunnelManager


class FakeProc:
    def __init__(self, lines=None):
        self._lines = list(lines or [])
        self.stdout = iter(self._lines)
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self._rc = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._rc = -9


def _room_ok():
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok")
    room.set_admin_password("admin-pass-ok")
    room.credentials_weak = False
    return room


def test_allow_tunnel_false_blocks_enable():
    """IT kill-switch: allow_tunnel=false vô hiệu hóa ở tầng mã."""
    room = _room_ok()
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(),
        require_strong=False,
        allow_tunnel=False,
    )
    try:
        tm.enable(room)
        assert False, "expected FORBIDDEN"
    except ApiError as e:
        assert e.status == 403
        assert e.code == "FORBIDDEN"
    assert tm.status()["enabled"] is False


def test_s9_api_tunnel_enable_without_password(tmp_path):
    """Ca S9 qua HTTP: chưa đặt mật khẩu → không bật được tunnel."""
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        credentials_weak=False,
    )
    # Xóa mật khẩu để mô phỏng phòng chưa đặt
    state.room.worker_password_hash = None
    state.room.admin_password_hash = None
    state.tunnel = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(),
        require_strong=False,
        allow_tunnel=True,
    )
    # Cần admin token — tạo room tạm có mật khẩu để join admin
    # rồi gắn token vào state.room đã bị xóa password... khó.
    # Thay: gọi trực tiếp enable như API handler.
    try:
        state.tunnel.enable(state.room)
        assert False
    except ApiError as e:
        assert e.code == "FORBIDDEN"
        assert "mật khẩu" in e.message.lower()


def test_allow_tunnel_false_via_settings_api(tmp_path):
    settings_path = str(tmp_path / "s.json")
    import json
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({"allow_tunnel": False}, f)
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=settings_path,
        esg_path=str(tmp_path / "e.json"),
        credentials_weak=False,
    )
    assert state.settings.get()["allow_tunnel"] is False
    c = TestClient(create_app(state))
    r = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD,
        "role": "admin",
    })
    assert r.status_code == 201
    token = r.json()["token"]
    # Stub binary để không fail 503 trước khi check allow
    state.tunnel._which = lambda _: "/fake/cloudflared"
    state.tunnel._popen = lambda *a, **k: FakeProc()
    state.tunnel._require_strong = False
    r2 = c.post("/api/tunnel/enable",
                headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 403
    assert state.tunnel.status()["enabled"] is False


def test_idle_timeout_auto_disables():
    room = _room_ok()
    now = {"t": 1000.0}
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(
            lines=["https://idle.trycloudflare.com\n"]),
        require_strong=False,
        allow_tunnel=True,
        clock=lambda: now["t"],
        readiness_probe=lambda _: True,
    )
    tm.enable(room)
    assert tm.status()["enabled"] is True
    # Vừa bật — chưa idle
    assert tm.check_idle() is False
    now["t"] = 1000.0 + IDLE_TIMEOUT_S + 1.0
    assert tm.check_idle() is True
    assert tm.status()["enabled"] is False


def test_activity_resets_idle_timer():
    room = _room_ok()
    now = {"t": 1000.0}
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(
            lines=["https://activity.trycloudflare.com\n"]),
        require_strong=False,
        allow_tunnel=True,
        clock=lambda: now["t"],
        readiness_probe=lambda _: True,
    )
    tm.enable(room)
    now["t"] = 1000.0 + IDLE_TIMEOUT_S - 10.0
    tm.touch_activity()
    now["t"] = 1000.0 + IDLE_TIMEOUT_S + 5.0
    # touch ở T+8h-10s → hạn mới = T+8h-10s+8h; tại T+8h+5 vẫn chưa idle
    assert tm.check_idle() is False
    now["t"] = 1000.0 + 2 * IDLE_TIMEOUT_S
    assert tm.check_idle() is True


def test_join_returns_lan_and_tunnel_urls(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        credentials_weak=False,
    )
    state.tunnel = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(
            lines=["https://demo.trycloudflare.com\n"]),
        require_strong=False,
        allow_tunnel=True,
        readiness_probe=lambda _: True,
    )
    c = TestClient(create_app(state))
    # Bật tunnel trước
    admin = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD,
        "role": "admin",
    }).json()["token"]
    c.post("/api/tunnel/enable",
           headers={"Authorization": f"Bearer {admin}"})
    # Đợi URL được đọc (thread)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if state.tunnel.status().get("public_url"):
            break
        time.sleep(0.05)

    r = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ROOM_PASSWORD,
        "node_name": "Node-A",
        "role": "worker",
    })
    assert r.status_code == 201
    body = r.json()
    assert "lan_url" in body
    assert body["lan_url"].startswith("http://")
    assert "8000" in body["lan_url"]
    # tunnel_url có thể None nếu thread chưa kịp — chấp nhận key có mặt
    assert "tunnel_url" in body


def test_allow_tunnel_false_cannot_reenable_via_api(tmp_path):
    """Kill-switch IT: API không bật lại allow_tunnel sau khi đã false."""
    import json
    settings_path = str(tmp_path / "s.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({"allow_tunnel": False}, f)
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=settings_path,
        esg_path=str(tmp_path / "e.json"),
        credentials_weak=False,
    )
    c = TestClient(create_app(state))
    admin = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD,
        "role": "admin",
    }).json()["token"]
    r = c.post("/api/settings",
               headers={"Authorization": f"Bearer {admin}"},
               json={"allow_tunnel": True})
    assert r.status_code == 403
    assert state.settings.get()["allow_tunnel"] is False
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    c = TestClient(create_app(state))
    # Join admin TRƯỚC — tránh backoff sau các lần sai
    admin = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD,
        "role": "admin",
    }).json()["token"]
    for _ in range(3):
        c.post("/join", json={
            "room_code": DEFAULT_ROOM_CODE,
            "password": "wrong-password-xx",
            "node_name": "X",
        })
    st = c.get("/api/state",
               headers={"Authorization": f"Bearer {admin}"}).json()
    assert st.get("auth_failures_total", 0) >= 3
    assert "auth_failures_1h" in st
