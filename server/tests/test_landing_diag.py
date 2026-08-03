"""Chẩn đoán landing tạo/tham gia — KHÔNG sửa production; chỉ assert hành vi.

Bypass: TestClient IP=testclient (loopback), POC_NO_BACKGROUND, không NodeAgent.
"""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from pathlib import Path

from fastapi.testclient import TestClient

from server import create_app, make_state


def _open(tmp_path):
    return make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )


def test_diag_create_then_admin_join_roundtrip(tmp_path):
    """Happy path: tạo phòng không token → join admin → state 200."""
    state = _open(tmp_path)
    c = TestClient(create_app(state))
    st = c.get("/api/room/status").json()
    assert st["bootstrap_open"] is True
    r = c.post("/api/room/bootstrap", json={
        "display_name": "Diag",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
        "regenerate_code": True,
    })
    assert r.status_code == 200, r.text
    code = r.json()["room"]["code"]
    assert code.startswith("THERMAL-")
    j = c.post("/join", json={
        "room_code": code,
        "password": "admin-pass-ok12",
        "role": "admin",
    })
    assert j.status_code == 201, j.text
    tok = j.json()["token"]
    s = c.get("/api/state", headers={"Authorization": f"Bearer {tok}"})
    assert s.status_code == 200
    assert s.json()["room"]["code"] == code


def test_diag_bootstrap_when_locked_without_token_is_401(tmp_path):
    """Bug class A: phòng đã khóa + không Bearer → 401 (không phải 'server chết')."""
    state = _open(tmp_path)
    c = TestClient(create_app(state))
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
    assert r.json()["error"]["code"] in ("AUTH_FAILED", "TOKEN_EXPIRED",
                                         "TOKEN_REVOKED", "FORBIDDEN")


def test_diag_wrong_password_then_rate_limit(tmp_path):
    """Bug class C/F: sai mật khẩu lặp → RATE_LIMITED (giống NodeAgent spam)."""
    state = _open(tmp_path)
    c = TestClient(create_app(state))
    boot = c.post("/api/room/bootstrap", json={
        "display_name": "R",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    }).json()["room"]["code"]
    codes = []
    for _ in range(8):
        r = c.post("/join", json={
            "room_code": boot,
            "password": "wrong-password-xx",
            "role": "admin",
        })
        codes.append(r.status_code)
        if r.status_code == 429:
            assert r.json()["error"]["code"] == "RATE_LIMITED"
            break
    assert 429 in codes, f"expected rate limit, got {codes}"


def test_diag_status_loopback_invite_after_lock(tmp_path):
    state = _open(tmp_path)
    c = TestClient(create_app(state))
    code = c.post("/api/room/bootstrap", json={
        "display_name": "L",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    }).json()["room"]["code"]
    st = c.get("/api/room/status").json()
    assert st["bootstrap_open"] is False
    assert st.get("code") == code
    assert "/join?code=" in (st.get("invite_lan") or "")


def test_diag_dashboard_html_contract():
    """UI contract: 2 tab landing, không tab đăng nhập cũ."""
    html = (Path(__file__).resolve().parents[1]
            / "static" / "dashboard.html").read_text(encoding="utf-8")
    assert "tabLogin" not in html
    assert "paneLogin" not in html
    assert "doCreateRoom" in html
    assert "doJoinLink" in html
    assert "Đăng nhập phòng này" not in html
