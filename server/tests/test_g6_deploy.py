"""G6 — dual URL, lan detect, installer paths, X6 stale khi mất kết nối."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from pathlib import Path

from fastapi.testclient import TestClient

from forecast_cache import NodeForecast
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, create_app, detect_lan_url,
                    make_state, run_forecast_cycle)
from store import TelemetryStore


def test_detect_lan_url_has_port():
    url = detect_lan_url(8000)
    assert url.startswith("http://")
    assert url.endswith(":8000")


def test_join_always_includes_endpoint_keys(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    c = TestClient(create_app(state))
    r = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ROOM_PASSWORD,
        "node_name": "Node-A",
        "role": "worker",
    })
    assert r.status_code == 201
    body = r.json()
    assert "lan_url" in body and body["lan_url"]
    assert "tunnel_url" in body  # có thể None khi tunnel tắt


def test_x6_lan_worker_unaffected_when_no_tunnel(tmp_path):
    """Ca X6 (phần LAN): không có tunnel → worker LAN vẫn READY."""
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    now = 1000.0
    for i in range(8):
        # Mẫu trong 40s gần nhất — last sample = now (không STALE)
        state.store.insert(
            "LAN-1", now - 40 + i * 5,
            45.0 + i * 0.1, None, 20.0, 30.0)
    run_forecast_cycle(state, now)
    fc = state.forecast_cache.get("LAN-1")
    assert fc is not None
    assert fc.state in ("READY", "WARMING_UP", "AT_RISK")
    # Tunnel tắt — LAN không phụ thuộc
    assert state.tunnel is None or state.tunnel.status()["enabled"] is False


def test_x6_silent_worker_becomes_stale(tmp_path):
    """Worker xa mất kết nối (không còn telemetry) → STALE sau cửa sổ."""
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
    )
    now = 5000.0
    # Mẫu cũ hơn STALE_AFTER_S (10s)
    state.store.insert("REMOTE-1", now - 30, 50.0, None, 10.0, 25.0)
    state.forecast_cache.put(NodeForecast(
        node="REMOTE-1", state="READY", predicted_max_c=55.0,
        last_sample_ts=now - 30, idle_baseline_c=40.0,
        effective_threshold_c=75.0, computed_at=now - 30,
    ))
    run_forecast_cycle(state, now)
    fc = state.forecast_cache.get("REMOTE-1")
    assert fc is not None
    assert fc.state == "STALE"


def test_installer_scripts_exist():
    root = Path(__file__).resolve().parents[2] / "installer"
    assert (root / "Install.ps1").is_file()
    assert (root / "Uninstall.ps1").is_file()
    assert (root / "FirstRun-Wizard.ps1").is_file()
    text = (root / "Uninstall.ps1").read_text(encoding="utf-8-sig")
    assert "GIU" in text.upper() or "GIỮ" in text or "Keep" in text
    assert "data" in text.lower()


def test_it_whitelist_doc_exists():
    doc = Path(__file__).resolve().parents[2] / "docs" / "IT-WHITELIST.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "KHÔNG CÓ" in text
    assert "SensorReader" in text
    assert "LOCALAPPDATA" in text
