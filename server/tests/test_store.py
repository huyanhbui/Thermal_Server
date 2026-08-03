from store import TelemetryStore

def test_insert_and_recent_orders_ascending_and_filters_window():
    s = TelemetryStore(":memory:")
    s.insert("Node-A", 100.0, 50.0, None, 10.0, 30.0)
    s.insert("Node-A", 104.0, 52.0, None, 20.0, 35.0)
    s.insert("Node-A", 10.0, 40.0, None, 5.0, 20.0)   # outside window
    s.insert("Node-B", 104.0, 60.0, 70.0, 90.0, 80.0)  # other node
    rows = s.recent("Node-A", seconds=60, now=105.0)
    assert [r["ts"] for r in rows] == [100.0, 104.0]
    assert rows[0]["cpu_temp"] == 50.0 and rows[0]["gpu_temp"] is None

def test_latest_and_nodes():
    s = TelemetryStore(":memory:")
    assert s.latest("Node-A") is None
    s.insert("Node-A", 1.0, 50.0, None, 10.0, 30.0)
    s.insert("Node-A", 2.0, 51.0, None, 11.0, 31.0)
    s.insert("Node-B", 2.0, 60.0, None, 12.0, 32.0)
    assert s.latest("Node-A")["cpu_temp"] == 51.0
    assert sorted(s.nodes()) == ["Node-A", "Node-B"]

def test_all_rows_returns_full_history_ascending():
    s = TelemetryStore(":memory:")
    s.insert("Node-A", 30.0, 40.0, None, 5.0, 20.0)
    s.insert("Node-A", 10.0, 35.0, None, 5.0, 20.0)
    s.insert("Node-B", 20.0, 50.0, None, 5.0, 20.0)
    rows = s.all_rows("Node-A")
    assert [r["ts"] for r in rows] == [10.0, 30.0]
    assert s.all_rows("missing") == []

def test_file_db_enables_wal(tmp_path):
    s = TelemetryStore(str(tmp_path / "t.db"))
    assert s.journal_mode().lower() == "wal"

def test_esg_events_append_and_read_back():
    s = TelemetryStore(":memory:")
    s.insert_esg_event(1.0, "Node-A", "flagged", {"pred": 76.0})
    s.insert_esg_event(2.0, "Node-A", "cleared", {"pred": 70.0})
    s.insert_esg_event(1.5, "Node-B", "flagged", None)
    ev = s.esg_events("Node-A")
    assert [e["event_type"] for e in ev] == ["flagged", "cleared"]
    assert ev[0]["detail"] == {"pred": 76.0}

def test_room_audit_hashes_ip_without_secrets_in_detail():
    s = TelemetryStore(":memory:")
    s.insert_room_audit(1.0, "127.0.0.1", "join_failed",
                        {"reason": "AUTH_FAILED", "node_name": "Node-A"})
    rows = s.room_audit_events()
    assert len(rows) == 1
    blob = str(rows[0])
    assert "password" not in blob.lower()
    assert "Bearer" not in blob
    assert rows[0]["ip"].startswith("sha256:")
    assert "127.0.0.1" not in str(rows[0])
