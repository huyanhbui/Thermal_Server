"""SQLite time-series store for node telemetry, ESG event ledger, and
room audit trail. One file, thread-safe via a lock. WAL mode so readers
(dashboard, forecast) do not block writers (ingest)."""
import csv
import hashlib
import io
import json
import logging
import sqlite3
import threading

log = logging.getLogger("store")

COLUMNS = ["node", "ts", "cpu_temp", "gpu_temp", "cpu_util", "power_w"]

_SENSITIVE_AUDIT_KEY_PARTS = (
    "password", "token", "secret", "authorization", "bearer", "cookie",
)


def _audit_ip_reference(ip: str | None) -> str | None:
    """Keep a stable correlation reference without retaining a raw IP address."""
    if not ip:
        return None
    return "sha256:" + hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _safe_audit_detail(value):
    """Recursively remove credentials before a value reaches SQLite or CSV."""
    if isinstance(value, dict):
        return {
            str(key): _safe_audit_detail(item)
            for key, item in value.items()
            if not any(part in str(key).lower()
                       for part in _SENSITIVE_AUDIT_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_safe_audit_detail(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_audit_detail(item) for item in value]
    return value

class TelemetryStore:
    def __init__(self, path=":memory:"):
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._last_checkpoint_at = 0.0
        with self._lock:
            # WAL is a no-op on :memory: but required for file DBs under
            # concurrent ingest + forecast + dashboard reads.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS telemetry ("
                "node TEXT NOT NULL, ts REAL NOT NULL, cpu_temp REAL, "
                "gpu_temp REAL, cpu_util REAL, power_w REAL)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_node_ts ON telemetry(node, ts)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS esg_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts REAL NOT NULL, node TEXT NOT NULL, "
                "event_type TEXT NOT NULL, detail_json TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS room_audit ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts REAL NOT NULL, ip TEXT, "
                "event_type TEXT NOT NULL, detail_json TEXT, "
                "role TEXT, node TEXT, request_id TEXT, source TEXT, "
                "result TEXT, error_code TEXT)")
            self._ensure_room_audit_columns()
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS room_auth ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
                "room_code TEXT NOT NULL, salt BLOB NOT NULL, "
                "worker_password_hash BLOB, admin_password_hash BLOB, "
                "worker_password_len INTEGER NOT NULL, "
                "admin_password_len INTEGER NOT NULL, generation INTEGER NOT NULL, "
                "credentials_weak INTEGER NOT NULL, display_name TEXT NOT NULL)")
            self._conn.commit()

    def _ensure_room_audit_columns(self) -> None:
        """Upgrade audit-only columns without rewriting old operational history."""
        existing = {
            row["name"] for row in self._conn.execute(
                "PRAGMA table_info(room_audit)").fetchall()
        }
        for name, sql_type in (
                ("role", "TEXT"), ("node", "TEXT"),
                ("request_id", "TEXT"), ("source", "TEXT"),
                ("result", "TEXT"), ("error_code", "TEXT")):
            if name not in existing:
                self._conn.execute(
                    f"ALTER TABLE room_audit ADD COLUMN {name} {sql_type}")

    def journal_mode(self):
        with self._lock:
            row = self._conn.execute("PRAGMA journal_mode").fetchone()
        return row[0] if row else None

    def maybe_wal_checkpoint(
            self, now: float, *, min_interval_s: float = 300.0) -> dict | None:
        """PASSIVE checkpoint có kiểm soát — log quan sát, không xóa DB."""
        if self._path == ":memory:":
            return None
        with self._lock:
            if now - self._last_checkpoint_at < min_interval_s:
                return None
            row = self._conn.execute(
                "PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            self._last_checkpoint_at = float(now)
            result = {
                "busy": int(row[0]) if row else 0,
                "wal_pages": int(row[1]) if row else 0,
                "checkpointed": int(row[2]) if row else 0,
            }
        log.info(
            "[STORE] WAL checkpoint PASSIVE busy=%d wal_pages=%d "
            "checkpointed=%d",
            result["busy"], result["wal_pages"], result["checkpointed"])
        return result

    def insert(self, node, ts, cpu_temp, gpu_temp, cpu_util, power_w):
        with self._lock:
            self._conn.execute(
                "INSERT INTO telemetry VALUES (?, ?, ?, ?, ?, ?)",
                (node, ts, cpu_temp, gpu_temp, cpu_util, power_w))
            self._conn.commit()

    def recent(self, node, seconds, now):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM telemetry WHERE node = ? AND ts >= ? AND ts <= ? "
                "ORDER BY ts ASC", (node, now - seconds, now)).fetchall()
        return [dict(r) for r in rows]

    def all_rows(self, node):
        """Every sample for a node, ascending by ts. Prefer this over
        recent(seconds=10**12) — intent is explicit and the planner can use
        the node index without a fake time window."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM telemetry WHERE node = ? ORDER BY ts ASC",
                (node,)).fetchall()
        return [dict(r) for r in rows]

    def latest(self, node):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM telemetry WHERE node = ? ORDER BY ts DESC LIMIT 1",
                (node,)).fetchone()
        return dict(row) if row else None

    def nodes(self):
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT node FROM telemetry").fetchall()
        return [r["node"] for r in rows]

    def insert_esg_event(self, ts, node, event_type, detail=None):
        detail_json = json.dumps(detail) if detail is not None else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO esg_events (ts, node, event_type, detail_json) "
                "VALUES (?, ?, ?, ?)",
                (ts, node, event_type, detail_json))
            self._conn.commit()

    def esg_events(self, node=None):
        with self._lock:
            if node is None:
                rows = self._conn.execute(
                    "SELECT ts, node, event_type, detail_json FROM esg_events "
                    "ORDER BY ts ASC, id ASC").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT ts, node, event_type, detail_json FROM esg_events "
                    "WHERE node = ? ORDER BY ts ASC, id ASC", (node,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("detail_json"):
                d["detail"] = json.loads(d["detail_json"])
            else:
                d["detail"] = None
            del d["detail_json"]
            out.append(d)
        return out

    def insert_room_audit(self, ts, ip, event_type, detail=None, *, role=None,
                          node=None, request_id=None, source=None, result=None,
                          error_code=None):
        """Append operational audit data after stripping secrets and raw IPs."""
        detail_json = json.dumps(
            _safe_audit_detail(detail), ensure_ascii=False,
            separators=(",", ":")) if detail is not None else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO room_audit ("
                "ts, ip, event_type, detail_json, role, node, request_id, "
                "source, result, error_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, _audit_ip_reference(ip), event_type, detail_json, role,
                 node, request_id, source, result, error_code))
            self._conn.commit()

    def room_audit_events(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, ip, event_type, detail_json, role, node, request_id, "
                "source, result, error_code FROM room_audit "
                "ORDER BY ts ASC, id ASC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("detail_json"):
                d["detail"] = json.loads(d["detail_json"])
            else:
                d["detail"] = None
            del d["detail_json"]
            out.append(d)
        return out

    def room_audit_csv(self) -> str:
        """Return an RFC 4180 CSV export of audit metadata, never secrets."""
        fields = ("ts", "ip", "event_type", "role", "node", "request_id",
                  "source", "result", "error_code", "detail_json")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for event in self.room_audit_events():
            writer.writerow({
                "ts": event["ts"], "ip": event["ip"],
                "event_type": event["event_type"], "role": event.get("role"),
                "node": event.get("node"),
                "request_id": event.get("request_id"),
                "source": event.get("source"), "result": event.get("result"),
                "error_code": event.get("error_code"),
                "detail_json": json.dumps(event.get("detail"),
                                          ensure_ascii=False,
                                          separators=(",", ":")),
            })
        return output.getvalue()

    def save_room_auth(self, *, room_code: str, salt: bytes,
                       worker_password_hash: bytes | None,
                       admin_password_hash: bytes | None,
                       worker_password_len: int, admin_password_len: int,
                       generation: int, credentials_weak: bool,
                       display_name: str = "") -> None:
        """Persist password verifiers only; session tokens deliberately stay RAM-only."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO room_auth (singleton, room_code, salt, "
                "worker_password_hash, admin_password_hash, worker_password_len, "
                "admin_password_len, generation, credentials_weak, display_name) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET room_code=excluded.room_code, "
                "salt=excluded.salt, worker_password_hash=excluded.worker_password_hash, "
                "admin_password_hash=excluded.admin_password_hash, "
                "worker_password_len=excluded.worker_password_len, "
                "admin_password_len=excluded.admin_password_len, "
                "generation=excluded.generation, "
                "credentials_weak=excluded.credentials_weak, "
                "display_name=excluded.display_name",
                (room_code, bytes(salt), worker_password_hash,
                 admin_password_hash, int(worker_password_len),
                 int(admin_password_len), int(generation),
                 int(bool(credentials_weak)), display_name))
            self._conn.commit()

    def load_room_auth(self) -> dict | None:
        """Load one verifier record; callers rebuild Room with no live tokens."""
        with self._lock:
            row = self._conn.execute(
                "SELECT room_code, salt, worker_password_hash, "
                "admin_password_hash, worker_password_len, admin_password_len, "
                "generation, credentials_weak, display_name "
                "FROM room_auth WHERE singleton = 1").fetchone()
        if row is None:
            return None
        data = dict(row)
        data["salt"] = bytes(data["salt"])
        for key in ("worker_password_hash", "admin_password_hash"):
            if data[key] is not None:
                data[key] = bytes(data[key])
        data["credentials_weak"] = bool(data["credentials_weak"])
        return data

    def close(self) -> None:
        """Close the database for deterministic tests and graceful shutdown."""
        with self._lock:
            self._conn.close()
