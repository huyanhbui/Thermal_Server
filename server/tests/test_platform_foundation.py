"""Regression tests for persistent room security and platform storage."""
from __future__ import annotations

import sqlite3

import pytest

from data_paths import DataMigrationConflict, prepare_database_path
from room import Room
from room_persist import load_room_auth, save_room_auth
from store import TelemetryStore
from tunnel import TunnelManager


class _TunnelProc:
    def __init__(self):
        self.stdout = iter(())
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self._rc = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._rc = -9


def test_thermal_data_dir_wins_and_migrates_one_legacy_database(tmp_path):
    legacy = tmp_path / "legacy.db"
    legacy.write_bytes(b"sqlite-data")
    data_dir = tmp_path / "chosen-data"

    destination = prepare_database_path(
        env={"THERMAL_DATA_DIR": str(data_dir)},
        legacy_paths=[str(legacy)],
    )

    assert destination == str(data_dir / "telemetry.db")
    assert (data_dir / "telemetry.db").read_bytes() == b"sqlite-data"
    assert legacy.read_bytes() == b"sqlite-data"


def test_database_migration_refuses_to_guess_between_two_nonempty_sources(tmp_path):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with pytest.raises(DataMigrationConflict):
        prepare_database_path(
            env={"THERMAL_DATA_DIR": str(tmp_path / "data")},
            legacy_paths=[str(first), str(second)],
        )


def test_database_migration_ignores_an_empty_sqlite_shell(tmp_path):
    """A newly created, empty DB file is not an ambiguous history source."""
    legacy = tmp_path / "legacy.db"
    legacy_conn = sqlite3.connect(legacy)
    legacy_conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY, temp REAL)")
    legacy_conn.execute("INSERT INTO telemetry (temp) VALUES (61.5)")
    legacy_conn.commit()
    legacy_conn.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    empty_conn = sqlite3.connect(data_dir / "telemetry.db")
    empty_conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY, temp REAL)")
    empty_conn.commit()
    empty_conn.close()

    destination = prepare_database_path(
        env={"THERMAL_DATA_DIR": str(data_dir)}, legacy_paths=[str(legacy)])

    assert destination == str(data_dir / "telemetry.db")
    with sqlite3.connect(destination) as migrated:
        assert migrated.execute("SELECT temp FROM telemetry").fetchone() == (61.5,)


def test_room_auth_verifiers_survive_store_reopen_without_plaintext(tmp_path):
    db = tmp_path / "telemetry.db"
    salt = b"0123456789abcdef"
    worker_hash = b"w" * 32
    admin_hash = b"a" * 32
    first = TelemetryStore(str(db))
    first.save_room_auth(
        room_code="THERMAL-ABCD", salt=salt,
        worker_password_hash=worker_hash, admin_password_hash=admin_hash,
        worker_password_len=14, admin_password_len=15,
        generation=7, credentials_weak=False, display_name="Phong A",
    )
    first.close()

    second = TelemetryStore(str(db))
    auth = second.load_room_auth()
    assert auth == {
        "room_code": "THERMAL-ABCD", "salt": salt,
        "worker_password_hash": worker_hash,
        "admin_password_hash": admin_hash,
        "worker_password_len": 14, "admin_password_len": 15,
        "generation": 7, "credentials_weak": False,
        "display_name": "Phong A",
    }
    raw = db.read_bytes().lower()
    assert b"worker-pass" not in raw
    second.close()


def test_room_persistence_rebuilds_auth_without_restoring_session_tokens():
    store = TelemetryStore(":memory:")
    original = Room(room_code="THERMAL-RESTORE", display_name="Phong khoi phuc")
    original.set_worker_password("worker-pass-ok12")
    original.set_admin_password("admin-pass-ok12")
    original.generation = 3
    token, _ = original.join(
        room_code="THERMAL-RESTORE", password="worker-pass-ok12",
        node_name="Node-A", role="worker", ip="127.0.0.1", now=10.0)
    save_room_auth(store, original)

    restored = load_room_auth(store)
    assert restored is not None
    assert restored.display_name == "Phong khoi phuc"
    assert restored.generation == 3
    with pytest.raises(Exception) as caught:
        restored.resolve(token, now=11.0)
    assert getattr(caught.value, "code", None) == "AUTH_FAILED"


def test_room_audit_hashes_ip_drops_secret_and_exports_csv():
    store = TelemetryStore(":memory:")
    store.insert_room_audit(
        10.0, "192.168.1.77", "tunnel_enabled",
        {"token": "do-not-keep", "reason": "ready"},
        role="admin", node="Host", request_id="req-1",
        source="tunnel", result="ok",
    )

    event = store.room_audit_events()[0]
    assert event["ip"].startswith("sha256:")
    assert "192.168.1.77" not in str(event)
    assert "token" not in str(event["detail"]).lower()
    assert event["source"] == "tunnel"
    csv_text = store.room_audit_csv()
    assert "tunnel_enabled" in csv_text
    assert "192.168.1.77" not in csv_text
    assert "do-not-keep" not in csv_text


def test_audit_schema_migrates_an_existing_database(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE room_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ts REAL NOT NULL, ip TEXT, event_type TEXT NOT NULL, detail_json TEXT)")
    conn.commit()
    conn.close()

    store = TelemetryStore(str(db))
    store.insert_room_audit(
        1.0, "127.0.0.1", "join_ok", {"role": "worker"},
        role="worker", node="Node-A", source="lan", result="ok")
    row = store.room_audit_events()[0]
    assert row["role"] == "worker"
    assert row["node"] == "Node-A"
    store.close()


def test_named_tunnel_requires_hostname_when_mode_is_explicit():
    room = Room(room_code="THERMAL-ABCD")
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    manager = TunnelManager(
        token="named-secret", which=lambda _name: "cloudflared",
        popen=lambda *_args, **_kwargs: _TunnelProc(), require_strong=False)

    with pytest.raises(Exception) as caught:
        manager.enable(room, mode="named")
    assert getattr(caught.value, "code", None) == "BAD_REQUEST"


def test_named_tunnel_uses_state_machine_and_audits_without_secret():
    room = Room(room_code="THERMAL-ABCD")
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    audit = []
    manager = TunnelManager(
        token="named-secret", hostname="thermal.example.com",
        which=lambda _name: "cloudflared",
        popen=lambda *_args, **_kwargs: _TunnelProc(),
        require_strong=False, readiness_probe=lambda _url: True,
        audit=lambda event, detail: audit.append((event, detail)))

    status = manager.enable(room, mode="named")
    assert status["state"] == "ready"
    assert status["public_url"] == "https://thermal.example.com"
    assert [event for event, _detail in audit][:2] == [
        "tunnel_enable_requested", "tunnel_enabled"]
    assert "named-secret" not in str(audit)
    manager.disable()
    assert manager.status()["state"] == "disabled"
