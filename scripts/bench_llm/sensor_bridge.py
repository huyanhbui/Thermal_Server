"""Ghi telemetry cục bộ bằng NodeAgent.exe --test-sensors.

Tránh phụ thuộc server/room khi đo G3. Mỗi mẫu ~ vài giây (nạp driver),
nên chu kỳ mặc định 3s. Schema khớp store.py để energy_per_token dùng được.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path


_TEMP_RE = re.compile(
    r"CPU\s*temp:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_POWER_RE = re.compile(
    r"Power:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_UTIL_RE = re.compile(
    r"CPU\s*util:\s*([0-9]+(?:\.[0-9]+)?)", re.I)


def parse_test_sensors(stdout: str) -> dict:
    out: dict = {
        "cpu_temp": None, "power_w": None, "cpu_util": None,
    }
    m = _TEMP_RE.search(stdout)
    if m:
        out["cpu_temp"] = float(m.group(1))
    m = _POWER_RE.search(stdout)
    if m:
        out["power_w"] = float(m.group(1))
    m = _UTIL_RE.search(stdout)
    if m:
        out["cpu_util"] = float(m.group(1))
    return out


class SensorBridge:
    def __init__(
        self,
        agent_exe: Path,
        db_path: Path,
        node: str,
        interval_s: float = 3.0,
    ):
        self.agent_exe = Path(agent_exe)
        self.db_path = Path(db_path)
        self.node = node
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples = 0
        self.last: dict | None = None
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS telemetry ("
                "node TEXT, ts REAL, cpu_temp REAL, gpu_temp REAL, "
                "cpu_util REAL, power_w REAL)"
            )
            conn.commit()
        finally:
            conn.close()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self.interval_s)

    def _sample_once(self) -> None:
        try:
            proc = subprocess.run(
                [str(self.agent_exe), "--test-sensors"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        parsed = parse_test_sensors(proc.stdout or "")
        self.last = parsed
        ts = time.time()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO telemetry VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.node, ts,
                    parsed["cpu_temp"], None,
                    parsed["cpu_util"], parsed["power_w"],
                ),
            )
            conn.commit()
            self.samples += 1
        finally:
            conn.close()
