"""API bootstrap / đóng phòng Host (docs/10 §1–2) + siết bảo mật."""
import json
import os
import re
from pathlib import Path

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state


def _open_client(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    return TestClient(create_app(state)), state


def test_bootstrap_open_creates_room_without_auth(tmp_path):
    c, state = _open_client(tmp_path)
    r = c.post("/api/room/bootstrap", json={
        "display_name": "Phòng 4F",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
        "site_id": "hanoi-office-4f",
        "threshold_c": 78,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    room = body["room"]
    assert room["display_name"] == "Phòng 4F"
    assert room["password_set"] is True
    assert room["code"].startswith("THERMAL-")
    assert room["code"] != "THERMAL-PENDING"
    assert "/join?code=" in room["invite_lan"]
    assert room["tunnel_ready"] is True
    meta = json.loads((tmp_path / "room.json").read_text(encoding="utf-8"))
    assert "password" not in meta
    assert "worker_password" not in meta
    assert meta["password_set"] is True
    assert meta["room_code"] == room["code"]
    assert state.settings.get()["threshold_c"] == 78.0


def test_bootstrap_rejects_non_loopback(tmp_path, monkeypatch):
    import server as srv
    c, _ = _open_client(tmp_path)
    monkeypatch.setattr(srv, "_client_ip", lambda _r: "192.168.1.50")
    r = c.post("/api/room/bootstrap", json={
        "display_name": "X",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_bootstrap_after_password_requires_admin(tmp_path):
    c, state = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "A",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    r = c.post("/api/room/bootstrap", json={
        "display_name": "B",
        "worker_password": "worker-pass-ok99",
        "admin_password": "admin-pass-ok99",
    })
    assert r.status_code == 401
    tok = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "admin-pass-ok12",
        "role": "admin",
    }).json()["token"]
    r2 = c.post("/api/room/bootstrap",
                headers={"Authorization": f"Bearer {tok}"},
                json={
                    "display_name": "B",
                    "worker_password": "worker-pass-ok99",
                    "admin_password": "admin-pass-ok99",
                    "regenerate_code": True,
                })
    assert r2.status_code == 200
    assert r2.json()["room"]["display_name"] == "B"
    # Token cũ bị thu hồi sau đổi mật khẩu
    dead = c.get("/api/state",
                 headers={"Authorization": f"Bearer {tok}"})
    assert dead.status_code in (401, 403)


def test_password_rotate_revokes_worker(tmp_path):
    c, state = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "X",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    wtok = c.post("/join", json={
        "room_code": code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "Node-A",
        "capabilities": {"cpu_cores": 2, "ram_gb": 4, "os": "t",
                         "has_gpu": False, "agent_version": "t"},
    }).json()["token"]
    atok = c.post("/join", json={
        "room_code": code,
        "password": "admin-pass-ok12",
        "role": "admin",
    }).json()["token"]
    r = c.post("/api/room/bootstrap",
               headers={"Authorization": f"Bearer {atok}"},
               json={
                   "display_name": "X2",
                   "worker_password": "worker-pass-ok99",
                   "admin_password": "admin-pass-ok99",
               })
    assert r.status_code == 200
    assert c.get("/api/state",
                 headers={"Authorization": f"Bearer {wtok}"}).status_code in (
                     401, 403)


def test_close_revokes_and_disables_tunnel(tmp_path):
    c, state = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "X",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    wtok = c.post("/join", json={
        "room_code": code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "Node-A",
        "capabilities": {"cpu_cores": 2, "ram_gb": 4, "os": "t",
                         "has_gpu": False, "agent_version": "t"},
    }).json()["token"]
    atok = c.post("/join", json={
        "room_code": code,
        "password": "admin-pass-ok12",
        "role": "admin",
    }).json()["token"]
    r = c.post("/api/room/close",
               headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200
    assert r.json()["revoked"] >= 1
    assert state.room.has_password() is False
    bad = c.get("/api/state", headers={"Authorization": f"Bearer {wtok}"})
    assert bad.status_code in (401, 403)
    # Sau close: bootstrap từ non-loopback vẫn 403
    import server as srv
    from unittest.mock import patch
    with patch.object(srv, "_client_ip", lambda _r: "10.0.0.8"):
        r2 = c.post("/api/room/bootstrap", json={
            "display_name": "Y",
            "worker_password": "worker-pass-ok12",
            "admin_password": "admin-pass-ok12",
        })
    assert r2.status_code == 403


def test_room_status_hides_code_when_locked_non_loopback(tmp_path, monkeypatch):
    import server as srv
    c, _ = _open_client(tmp_path)
    open_st = c.get("/api/room/status").json()
    assert open_st["bootstrap_open"] is True
    c.post("/api/room/bootstrap", json={
        "display_name": "Z",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    monkeypatch.setattr(srv, "_client_ip", lambda _r: "192.168.1.50")
    locked = c.get("/api/room/status").json()
    assert locked["bootstrap_open"] is False
    assert "code_hint" not in locked
    assert "code" not in locked
    assert "invite_lan" not in locked


def test_room_status_loopback_exposes_invite_when_locked(tmp_path):
    c, state = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "Z",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    # TestClient IP = testclient → coi là loopback
    locked = c.get("/api/room/status").json()
    assert locked["bootstrap_open"] is False
    assert locked.get("code") == state.room.room_code
    assert "/join?code=" in (locked.get("invite_lan") or "")


def test_reopen_bootstrap_loopback_clears_password(tmp_path):
    c, state = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "Live",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    code = state.room.room_code
    wtok = c.post("/join", json={
        "room_code": code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "Node-A",
        "capabilities": {"cpu_cores": 2, "ram_gb": 4, "os": "t",
                         "has_gpu": False, "agent_version": "t"},
    }).json()["token"]
    assert c.get("/api/room/status").json()["bootstrap_open"] is False
    r = c.post("/api/room/reopen-bootstrap")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bootstrap_open"] is True
    assert body["revoked"] >= 1
    assert state.room.has_password() is False
    assert c.get("/api/room/status").json()["bootstrap_open"] is True
    dead = c.get("/api/state", headers={"Authorization": f"Bearer {wtok}"})
    assert dead.status_code in (401, 403)
    # Sau reopen: bootstrap ẩn danh lại được
    r2 = c.post("/api/room/bootstrap", json={
        "display_name": "Moi",
        "worker_password": "worker-pass-new12",
        "admin_password": "admin-pass-new12",
        "regenerate_code": True,
    })
    assert r2.status_code == 200
    assert r2.json()["room"]["password_set"] is True
    events = state.store.room_audit_events()
    assert any(e["event_type"] == "room_reopen_bootstrap" for e in events)


def test_get_join_redirects_to_landing_with_code(tmp_path):
    c, _ = _open_client(tmp_path)
    r = c.get("/join?code=THERMAL-ABCD", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/?code=THERMAL-ABCD"
    r2 = c.get("/join", follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/"


def test_join_reclaims_stale_node_name(tmp_path):
    from errors import ApiError
    from room import NODE_RECLAIM_AFTER_S, Room
    room = Room(room_code="THERMAL-TEST", capacity=10)
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    now = 1_000_000.0
    tok1, _ = room.join(
        room_code="THERMAL-TEST", password="worker-pass-ok12",
        node_name="Node-A", role="worker", ip="10.0.0.1", now=now)
    assert tok1
    try:
        room.join(
            room_code="THERMAL-TEST", password="worker-pass-ok12",
            node_name="Node-A", role="worker", ip="10.0.0.1",
            now=now + 10.0)
        assert False, "expected NODE_NAME_TAKEN"
    except ApiError as e:
        assert e.code == "NODE_NAME_TAKEN"
    tok2, _ = room.join(
        room_code="THERMAL-TEST", password="worker-pass-ok12",
        node_name="Node-A", role="worker", ip="10.0.0.1",
        now=now + NODE_RECLAIM_AFTER_S + 1.0)
    assert tok2
    assert tok2 != tok1


def test_reopen_bootstrap_rejects_non_loopback(tmp_path, monkeypatch):
    import server as srv
    c, _ = _open_client(tmp_path)
    c.post("/api/room/bootstrap", json={
        "display_name": "X",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    })
    monkeypatch.setattr(srv, "_client_ip", lambda _r: "192.168.1.50")
    r = c.post("/api/room/reopen-bootstrap")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    assert c.get("/api/room/status").json()["bootstrap_open"] is False


def test_dashboard_has_no_login_tab():
    html = Path(__file__).resolve().parents[1] / "static" / "dashboard.html"
    text = html.read_text(encoding="utf-8")
    assert "tabLogin" not in text
    assert "paneLogin" not in text
    assert "Đăng nhập phòng này" not in text
    assert "Máy này là Host của phòng dưới đây" not in text
    assert "rolesHint" not in text
    assert "showLandingTab('join')" in text or 'showLandingTab("join")' in text
    assert "doCreateRoom" in text
    assert "doReopenBootstrap" in text
    assert "btnReopenBootstrap" in text
    assert "/api/room/reopen-bootstrap" in text
    assert "goJoinOtherRoom" in text
    assert "doReopenFromApp" in text
    assert "createNewCode" in text
    assert "bootName.value" in text or "bootName').value" in text


def test_room_json_rejects_password_keys(tmp_path):
    from room_persist import save_room_meta, load_room_meta
    path = str(tmp_path / "room.json")
    save_room_meta(path, {
        "display_name": "Z",
        "password": "should-not-save",
        "worker_password": "nope",
        "password_set": True,
        "room_code": "THERMAL-ABCD",
    })
    raw = (tmp_path / "room.json").read_text(encoding="utf-8")
    assert "should-not-save" not in raw
    assert "nope" not in raw
    meta = load_room_meta(path)
    assert meta["display_name"] == "Z"
    assert "password" not in meta


def test_dashboard_script_brace_balanced():
    html = Path(__file__).resolve().parents[1] / "static" / "dashboard.html"
    text = html.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", text, re.S)
    assert m, "missing script"
    bal = 0
    for ch in m.group(1):
        if ch == "{":
            bal += 1
        elif ch == "}":
            bal -= 1
            assert bal >= 0, "extra closing brace"
    assert bal == 0


def test_uninstall_requires_delete_esg_phrase():
    root = Path(__file__).resolve().parents[2]
    text = (root / "installer" / "Uninstall.ps1").read_text(encoding="utf-8")
    assert "DELETE-ESG" in text
    assert '($ans -eq "yes"' not in text
    assert "-ConfirmRemoveData" in text
