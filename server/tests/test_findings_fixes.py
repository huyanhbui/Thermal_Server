"""Test cho các finding #6–#12, #17, #18 (review thiết kế)."""
from __future__ import annotations

import csv
import io
import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

import pytest
from fastapi.testclient import TestClient

from server import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ROOM_CODE,
    DEFAULT_ROOM_PASSWORD,
    SERVER_PORT,
    STALE_AFTER_S,
    build_state_payload,
    create_app,
    make_state,
    refresh_weather,
    run_forecast_cycle,
)


def _state(tmp_path):
    return make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )


def _join(client, node="Node-A", role="worker"):
    pw = DEFAULT_ADMIN_PASSWORD if role == "admin" else DEFAULT_ROOM_PASSWORD
    body = {"room_code": DEFAULT_ROOM_CODE, "password": pw, "role": role}
    if role == "worker":
        body["node_name"] = node
        body["capabilities"] = {
            "cpu_cores": 2, "ram_gb": 4, "os": "t",
            "has_gpu": False, "agent_version": "t",
        }
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── #6 POC_PORT ──────────────────────────────────────────────────────

def test_uvicorn_uses_server_port(monkeypatch, tmp_path):
    """run_server → uvicorn.run dùng SERVER_PORT."""
    import server as srv
    import uvicorn as uv
    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(srv, "SERVER_PORT", 9123)
    monkeypatch.setattr(uv, "run", fake_run)
    application = create_app(_state(tmp_path))
    srv.run_server(application)
    assert captured.get("port") == 9123


def test_run_server_respects_explicit_port(monkeypatch, tmp_path):
    import server as srv
    import uvicorn as uv
    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(uv, "run", fake_run)
    srv.run_server(create_app(_state(tmp_path)), port=7777)
    assert captured.get("port") == 7777


def test_tunnel_manager_local_url_matches_server_port(tmp_path, monkeypatch):
    import server as srv
    monkeypatch.setattr(srv, "SERVER_PORT", 8765)
    state = srv.make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    assert state.tunnel.local_url == "http://127.0.0.1:8765"


# ── #7 /ingest 202 ───────────────────────────────────────────────────

def test_ingest_returns_202(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    tok = _join(c)
    r = c.post(
        "/ingest", headers=_auth(tok),
        json={"cpu_temp": 42.0, "cpu_util": 10, "power_source": "none"},
    )
    assert r.status_code == 202
    assert r.json()["ok"] is True


# ── #8 Logging UTF-8 ─────────────────────────────────────────────────

def test_logging_handlers_utf8_vietnamese():
    import logging

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers
                     if isinstance(h, logging.FileHandler)]
    assert file_handlers, "cần FileHandler với encoding=utf-8"
    for h in file_handlers:
        assert str(getattr(h, "encoding", "")).lower() == "utf-8"
    # Ghi tiếng Việt không được ném UnicodeEncodeError
    logging.getLogger("server").info(
        "Cảnh báo: nhiệt độ vượt ngưỡng — kiểm tra tản nhiệt")


def test_configure_logging_idempotent_no_duplicate_handlers():
    import logging
    import server as srv
    root = logging.getLogger()
    before = len(root.handlers)
    srv.configure_logging()
    srv.configure_logging()
    after = len(root.handlers)
    assert after == before
    # Gọi lại không xóa UTF-8
    files = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert files
    for h in files:
        assert "utf" in str(getattr(h, "encoding", "")).lower()


# ── #9 DoS WS + jobs/next ────────────────────────────────────────────

def test_jobs_next_rate_limit_30_per_minute(tmp_path):
    from rate_limit import JOBS_MAX
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    tok = _join(c)
    codes = []
    for _ in range(JOBS_MAX + 3):
        r = c.get("/jobs/next?wait=0", headers=_auth(tok))
        codes.append(r.status_code)
    assert 429 in codes
    assert codes.count(200) + codes.count(204) >= JOBS_MAX


def test_jobs_next_normal_poll_still_ok(tmp_path):
    c = TestClient(create_app(_state(tmp_path)))
    tok = _join(c)
    for _ in range(5):
        r = c.get("/jobs/next?wait=0", headers=_auth(tok))
        assert r.status_code in (200, 204)


def test_ws_auth_quota_per_token_and_ip(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")
    # 2 socket/token OK
    with c.websocket_connect("/ws") as ws1:
        ws1.send_json({"type": "auth", "token": admin})
        ws1.receive_json()
        with c.websocket_connect("/ws") as ws2:
            ws2.send_json({"type": "auth", "token": admin})
            ws2.receive_json()
            # Socket thứ 3 cùng token → từ chối
            with pytest.raises(Exception):
                with c.websocket_connect("/ws") as ws3:
                    ws3.send_json({"type": "auth", "token": admin})
                    ws3.receive_json(timeout=2)


# ── #10 weather non-block ────────────────────────────────────────────

def test_slow_weather_refresh_does_not_block_api(tmp_path):
    state = _state(tmp_path)
    barrier = threading.Event()
    started = threading.Event()

    def slow_fetch(site, cfg, now):
        started.set()
        barrier.wait(timeout=5.0)
        return {"temp_c": 30.0, "feels_like_c": 32.0}

    state.weather._fetch_fn = slow_fetch
    state.weather._cfg["enabled"] = True
    state.weather._cfg["api_key"] = "k"
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")

    def do_refresh():
        refresh_weather(state, time.time())

    t = threading.Thread(target=do_refresh)
    t.start()
    assert started.wait(timeout=2.0)
  # API vẫn phản hồi khi refresh đang chặn trong thread
    r = c.get("/api/state", headers=_auth(admin))
    assert r.status_code == 200
    barrier.set()
    t.join(timeout=3.0)


def test_weather_snapshot_reads_cache_only(tmp_path):
    svc = _state(tmp_path).weather
    svc._cache["hanoi-office-4f"] = {
        "temp_c": 25.0, "feels_like_c": 26.0,
        "updated_at": 100.0, "site_id": "hanoi-office-4f",
    }
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise RuntimeError("should not fetch")

    svc._fetch_fn = boom
    snap = svc.snapshot(now=110.0)
    assert snap["hanoi-office-4f"]["temp_c"] == 25.0
    assert called["n"] == 0


# ── #12 node name + CSV ──────────────────────────────────────────────

@pytest.mark.parametrize("bad_name", [
    "Node\nA", "a,b", "=CMD()", "+evil", "@inject",
    "", " " * 3, "x" * 65,
])
def test_join_rejects_invalid_node_name(tmp_path, bad_name):
    c = TestClient(create_app(_state(tmp_path)))
    pw = DEFAULT_ROOM_PASSWORD
    body = {
        "room_code": DEFAULT_ROOM_CODE, "password": pw, "role": "worker",
        "node_name": bad_name,
        "capabilities": {"cpu_cores": 2, "ram_gb": 4, "os": "t",
                         "has_gpu": False, "agent_version": "t"},
    }
    r = c.post("/join", json=body)
    assert r.status_code in (400, 422)


def test_esg_csv_formula_injection_safe(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")
    state.store.insert_esg_event(
        1.0, "=HYPERLINK()", "flagged",
        {"pred": 90, "threshold_at_time": 75.0})
    r = c.get("/api/esg.csv", headers=_auth(admin))
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) >= 2
    node_cell = rows[1][1]
    assert not node_cell.startswith("=")


# ── #17 stale telemetry ──────────────────────────────────────────────

def test_stale_node_payload_not_live(tmp_path):
    state = _state(tmp_path)
    now = 1000.0
    _join(TestClient(create_app(state)), "Node-A")
    state.store.insert("Node-A", now - STALE_AFTER_S - 5, 72.0, None, 90.0, 40.0)
    run_forecast_cycle(state, now)
    fc = state.forecast_cache.get("Node-A")
    assert fc is not None and fc.state == "STALE"
    payload = build_state_payload(state, now)
    node = next(n for n in payload["nodes"] if n["name"] == "Node-A")
    assert node["stale"] is True
    assert node.get("live") is False
    assert node["cpu_temp"] is None
    assert node["predicted_max"] is None
    assert payload["forecast_source"] in ("linear_fallback", "ml")


def test_no_active_nodes_empty_list(tmp_path):
    state = _state(tmp_path)
    payload = build_state_payload(state, time.time())
    assert payload["nodes"] == []


# ── #18 WAL observability ────────────────────────────────────────────

def test_wal_passive_checkpoint_logs(tmp_path):
    from store import TelemetryStore
    db = str(tmp_path / "t.db")
    store = TelemetryStore(db)
    assert store.journal_mode() == "wal"
    result = store.maybe_wal_checkpoint(1000.0, min_interval_s=0.0)
    assert result is not None
    assert "checkpointed" in result
    assert store.maybe_wal_checkpoint(1001.0, min_interval_s=300.0) is None
    assert store.maybe_wal_checkpoint(1400.0, min_interval_s=300.0) is not None


def test_weather_loop_uses_to_thread():
    """Chứng minh _weather_loop bọc refresh bằng asyncio.to_thread."""
    import inspect
    import server as srv
    src = inspect.getsource(srv._weather_loop)
    assert "asyncio.to_thread" in src
    assert "refresh_weather" in src
    # Không gọi refresh trực tiếp trên event loop
    assert "await refresh_weather" not in src
    assert "refresh_weather(state" not in src.replace(
        "asyncio.to_thread(refresh_weather", "")


def test_invalidate_state_cache_on_room_close(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")
    from server import _cached_state_payload
    _cached_state_payload(state, time.time())
    assert state._state_payload_cache
    c.post("/api/room/close", headers=_auth(admin))
    assert state._state_payload_cache == {}


def test_wal_loop_wired_for_calibrate_mode():
    import inspect
    import server as srv
    src = inspect.getsource(srv.create_app)
    assert "_wal_loop" in src
    # Cả nhánh calibrate và non-calibrate
    assert src.count("_wal_loop") >= 2
