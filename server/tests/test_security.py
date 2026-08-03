"""Ca bảo mật S1–S15 (docs/11 §6) và C7 — trừ S10/S11 (Downloader = G4)."""
import os
import time
os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient
from room import AUTH_FAILED_MSG, Room
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, create_app, make_state)

def _state(tmp_path):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "m.pkl"),
                      settings_path=str(tmp_path / "s.json"),
                      esg_path=str(tmp_path / "e.json"))

def _client(tmp_path):
    return TestClient(create_app(_state(tmp_path))), None

def join(client, node=None, role="worker", password=None,
         room_code=DEFAULT_ROOM_CODE):
    if password is None:
        password = (DEFAULT_ADMIN_PASSWORD if role == "admin"
                    else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": room_code, "password": password, "role": role}
    if role == "worker":
        body["node_name"] = node or "Node-X"
        body["capabilities"] = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
                                "has_gpu": False, "agent_version": "t"}
    return client.post("/join", json=body)

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_s1_ingest_without_token_is_401(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    r = c.post("/ingest", json={"cpu_temp": 50, "power_source": "none"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] in ("AUTH_FAILED", "TOKEN_EXPIRED",
                                         "TOKEN_REVOKED")

def test_s2_body_node_mismatch_is_403_and_audited(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = join(c, "Node-A").json()["token"]
    r = c.post("/ingest", headers=auth(tok),
               json={"node": "Node-B", "cpu_temp": 40, "power_source": "none"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "IDENTITY_MISMATCH"
    events = state.store.room_audit_events()
    assert any(e["event_type"] == "identity_mismatch" for e in events)

def test_s3_query_node_ignored_token_wins(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok_a = join(c, "Node-A").json()["token"]
    tok_b = join(c, "Node-B").json()["token"]
    now = time.time()
    for tok, temp in ((tok_a, 40.0), (tok_b, 40.0)):
        c.post("/ingest", headers=auth(tok),
               json={"ts": now, "cpu_temp": temp, "cpu_util": 10,
                     "power_w": 20, "power_source": "sensor"})
    # Đủ mẫu để READY — seed thêm vài điểm
    for i in range(8):
        for name, tok in (("Node-A", tok_a), ("Node-B", tok_b)):
            state.store.insert(name, now - 80 + i * 10, 40.0, None, 10.0, 20.0)
    from server import run_forecast_cycle, run_scheduler_cycle
    run_forecast_cycle(state, now)
    state.balancer.enqueue_job()
    run_scheduler_cycle(state, now)
    # Claim Node-B in query while holding Node-A token → still Node-A's poll
    r = c.get("/jobs/next?wait=0", headers=auth(tok_a),
              params={"node": "Node-B"})
    assert r.status_code in (200, 204)
    if r.status_code == 200:
        assert state.balancer.stats()["dispatched"].get("Node-A", 0) == 1
        assert state.balancer.stats()["dispatched"].get("Node-B", 0) == 0
def test_s4_worker_cannot_change_settings(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    tok = join(c, "Node-A").json()["token"]
    r = c.post("/api/settings", headers=auth(tok), json={"threshold_c": 80})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"

def test_s5_join_rate_limit_after_failed_attempts(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    codes = []
    for _ in range(10):
        r = join(c, "Node-A", password="wrong-password!!")
        codes.append(r.status_code)
    assert 401 in codes
    assert 429 in codes
    # S5: within a burst of failures, rate limit must kick in
    assert codes.index(429) <= 5 or any(
        c == 429 for c in codes[5:])


def test_worker_fail_burst_does_not_rate_limit_admin_same_ip(tmp_path):
    """Bucket theo ip|role — worker spam không khóa admin cùng IP."""
    c = TestClient(create_app(_state(tmp_path)))
    for i in range(8):
        r = join(c, f"Node-W{i}", password="wrong-password!!")
        assert r.status_code in (401, 429)
    r_admin = join(c, role="admin")
    assert r_admin.status_code == 201, r_admin.text


def test_join_success_clears_fail_window_for_role(tmp_path):
    """Join đúng xóa cửa sổ fail — không 429 ngay sau khi vừa thành công."""
    room = Room(room_code=DEFAULT_ROOM_CODE, capacity=10)
    room.set_worker_password(DEFAULT_ROOM_PASSWORD)
    room.set_admin_password(DEFAULT_ADMIN_PASSWORD)
    now = 1_000_000.0
    ip = "10.0.0.9"
    for _ in range(4):
        try:
            room.join(
                room_code=DEFAULT_ROOM_CODE, password="bad-pass-xx",
                node_name="Node-X", role="worker", ip=ip, now=now)
        except Exception:
            pass
        now += 1.0
    tok, _ = room.join(
        room_code=DEFAULT_ROOM_CODE, password=DEFAULT_ROOM_PASSWORD,
        node_name="Node-Ok", role="worker", ip=ip, now=now)
    assert tok
    key = Room._rate_key(ip, "worker")
    assert key not in room._fail_ts
    # Fail mới sau success — không còn dính cửa sổ cũ
    now += 1.0
    try:
        room.join(
            room_code=DEFAULT_ROOM_CODE, password="bad-again!!",
            node_name="Node-Y", role="worker", ip=ip, now=now)
    except Exception:
        pass
    assert len(room._fail_ts.get(key, [])) == 1


def test_s6_kicked_token_is_revoked(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    tok = join(c, "Node-A").json()["token"]
    admin = join(c, role="admin").json()["token"]
    assert c.post("/api/nodes/Node-A/kick", headers=auth(admin)).status_code == 200
    r = c.post("/ingest", headers=auth(tok),
               json={"cpu_temp": 40, "power_source": "none"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_REVOKED"

def test_s7_expired_token_rejected(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = join(c, "Node-A").json()["token"]
    state.room.force_expire(tok, expires_at=1.0)
    r = c.post("/ingest", headers=auth(tok),
               json={"cpu_temp": 40, "power_source": "none"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_EXPIRED"

def test_s8_wrong_code_and_password_same_message(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    r1 = join(c, "Node-A", password="wrong-password!!")
    r2 = join(c, "Node-A", room_code="WRONG-CODE", password=DEFAULT_ROOM_PASSWORD)
    assert r1.status_code == 401 and r2.status_code == 401
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]
    assert r1.json()["error"]["message"] == AUTH_FAILED_MSG

def test_s9_tunnel_blocked_without_password():
    room = Room(room_code="X")
    assert not room.has_password()
    try:
        room.enable_tunnel()
        assert False, "should have raised"
    except Exception as e:
        from errors import ApiError
        assert isinstance(e, ApiError)
        assert e.code == "FORBIDDEN"

def test_s12_room_audit_has_no_secrets(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    join(c, "Node-A", password="wrong-password!!")
    join(c, "Node-A")
    blob = str(state.store.room_audit_events()).lower()
    assert "password" not in blob
    assert "bearer" not in blob
    assert "local-dev-password" not in blob
    assert "local-admin-password" not in blob

def test_s14_threshold_below_40_rejected(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    admin = join(c, role="admin").json()["token"]
    r = c.post("/api/settings", headers=auth(admin), json={"threshold_c": 20})
    # Pydantic ge=40 → BAD_REQUEST 400 via our handler, or 422 from framework
    assert r.status_code in (400, 422)

def test_s15_ghost_ingest_without_token_no_dashboard(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    assert c.post("/ingest", json={
        "node": "Ghost", "cpu_temp": 20, "power_source": "none"}).status_code == 401
    admin = join(c, role="admin").json()["token"]
    names = [n["name"] for n in c.get("/api/state", headers=auth(admin)).json()["nodes"]]
    assert "Ghost" not in names

def test_worker_state_payload_is_compact(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    worker = join(c, "Node-A").json()["token"]
    admin = join(c, role="admin").json()["token"]
    w = c.get("/api/state", headers=auth(worker)).json()
    a = c.get("/api/state", headers=auth(admin)).json()
    assert "esg" not in w
    assert "esg" in a
    if w["nodes"]:
        assert set(w["nodes"][0].keys()) <= {"name", "state", "cpu_temp"}

def test_c7_ten_workers_same_ip_not_rate_limited(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    tokens = []
    for i in range(10):
        r = join(c, f"Node-{i:02d}")
        assert r.status_code == 201, r.text
        tokens.append(r.json()["token"])
    assert len(set(tokens)) == 10
    r11 = join(c, "Node-10")
    assert r11.status_code == 409
    assert r11.json()["error"]["code"] == "ROOM_FULL"


def test_worker_password_cannot_join_as_admin(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    r = join(c, role="admin", password=DEFAULT_ROOM_PASSWORD)
    assert r.status_code == 401


def test_admin_password_cannot_join_as_worker(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    r = join(c, "Node-A", role="worker", password=DEFAULT_ADMIN_PASSWORD)
    assert r.status_code == 401


def test_ingest_rate_limit_429(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = join(c, "Node-A").json()["token"]
    codes = []
    for _ in range(5):
        r = c.post("/ingest", headers=auth(tok),
                   json={"cpu_temp": 40, "power_source": "none"})
        codes.append(r.status_code)
    assert 429 in codes


def test_ws_auth_via_first_message(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    admin = join(c, role="admin").json()["token"]
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": admin})
        msg = ws.receive_json()
        assert "nodes" in msg
        assert "esg" in msg


def test_tunnel_enable_without_binary_is_503(tmp_path):
    state = _state(tmp_path)
    # Ép không tìm thấy binary
    state.tunnel._binary_override = None
    state.tunnel._which = lambda _: None
    state.tunnel._require_strong = False
    c = TestClient(create_app(state))
    admin = join(c, role="admin").json()["token"]
    r = c.post("/api/tunnel/enable", headers=auth(admin))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "TUNNEL_UNAVAILABLE"
    assert state.tunnel.status()["enabled"] is False
