"""P2/P3: stale từ store sau restart, logging cp1252, lifecycle now bắt buộc."""
from __future__ import annotations

import logging
import os
import time

os.environ["POC_NO_BACKGROUND"] = "1"

import pytest

from room import make_default_room
from server import (
    STALE_AFTER_S,
    build_state_payload,
    configure_logging,
    make_state,
    nodes_for_payload,
)


def test_stale_node_from_store_after_restart_empty_cache(tmp_path):
    """Telemetry trong ACTIVE_WINDOW + AppState mới/cache rỗng → STALE."""
    db = str(tmp_path / "telemetry.db")
    from store import TelemetryStore
    from server import ACTIVE_WINDOW_S
    old = TelemetryStore(db)
    # Cũ hơn STALE_AFTER nhưng còn trong ACTIVE_WINDOW (không phải ghost)
    old_ts = time.time() - STALE_AFTER_S - 120.0
    assert time.time() - old_ts < ACTIVE_WINDOW_S
    old.insert("Node-Restart", old_ts, 71.0, None, 40.0, 35.0)
    del old

    state = make_state(
        db_path=db,
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
    )
    assert "Node-Restart" not in state.forecast_cache.all()
    now = time.time()
    names = nodes_for_payload(state, now)
    assert "Node-Restart" in names
    payload = build_state_payload(state, now)
    node = next(n for n in payload["nodes"] if n["name"] == "Node-Restart")
    assert node["state"] == "STALE"
    assert node.get("stale") is True
    assert node.get("cpu_temp") is None


def test_configure_logging_replaces_cp1252_file_handler(tmp_path):
    root = logging.getLogger()
    bad_path = str(tmp_path / "bad.log")
    # Giả handler file encoding lệch (Windows cp1252)
    bad = logging.FileHandler(bad_path, encoding="cp1252")
    bad.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(bad)
    try:
        configure_logging(log_file=str(tmp_path / "server-utf8.log"))
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.FileHandler)
        ]
        assert file_handlers
        for h in file_handlers:
            enc = str(getattr(h, "encoding", "") or "").lower()
            assert "utf" in enc, f"còn handler encoding={enc!r}"
        logging.getLogger("server").info(
            "Cảnh báo: nhiệt độ vượt ngưỡng — kiểm tra tản nhiệt")
    finally:
        # Dọn handler test — không để lại cp1252
        for h in list(root.handlers):
            if isinstance(h, logging.FileHandler):
                path = getattr(h, "baseFilename", "")
                if "bad.log" in path or "server-utf8.log" in path:
                    root.removeHandler(h)
                    h.close()
        configure_logging()


def test_lifecycle_close_requires_now_no_internal_time():
    import inspect
    from room import Room
    src = inspect.getsource(Room.lifecycle_close)
    assert "time.time()" not in src
    room = make_default_room()
    n = room.lifecycle_close(now=1_700_000_000.0)
    assert n >= 0
    with pytest.raises(TypeError):
        room.lifecycle_close()  # type: ignore[call-arg]


def test_lifecycle_rotate_requires_now():
    import inspect
    from room import Room
    src = inspect.getsource(Room.lifecycle_rotate_passwords)
    assert "time.time()" not in src
    room = make_default_room()
    n = room.lifecycle_rotate_passwords(
        "worker-pass-ok12", "admin-pass-ok12", now=1_700_000_001.0)
    assert n >= 0
    with pytest.raises(TypeError):
        room.lifecycle_rotate_passwords(
            "worker-pass-ok12", "admin-pass-ok12")  # type: ignore[call-arg]
