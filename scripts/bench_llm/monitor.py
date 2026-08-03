"""Theo dõi RAM đỉnh tiến trình và nhiệt CPU từ telemetry.

Harness độc lập — không phải phần hệ thống. Nhiệt ưu tiên đọc từ
telemetry.db (agent đang chạy). RAM lấy Working Set qua Win32.
"""
from __future__ import annotations

import ctypes
import sqlite3
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field


@dataclass
class PeakMonitor:
    """Lấy mẫu RAM của một PID theo chu kỳ; ghi đỉnh."""

    pid: int
    interval_s: float = 0.25
    peak_rss_bytes: int = 0
    samples: int = 0
    method: str = "win32"
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            rss = process_rss_bytes(self.pid)
            if rss is not None and rss > self.peak_rss_bytes:
                self.peak_rss_bytes = rss
            self.samples += 1
            self._stop.wait(self.interval_s)

    @property
    def peak_rss_mb(self) -> float:
        return self.peak_rss_bytes / (1024 * 1024)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_rss_bytes(pid: int) -> int | None:
    """Working set hiện tại của PID; None nếu tiến trình đã chết.

    Dùng WorkingSetSize (snapshot), không PeakWorkingSetSize — tránh
    kế thừa đỉnh đời process khi ONNX chạy trong cùng PID Python.
    """
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    access = (
        PROCESS_QUERY_INFORMATION
        | PROCESS_QUERY_LIMITED_INFORMATION
        | PROCESS_VM_READ
    )
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def peak_temp_from_telemetry(
    db_path: str, node: str, t_from: float, t_to: float,
) -> float | None:
    """MAX(cpu_temp) trong cửa sổ thời gian; None nếu không có mẫu."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT MAX(cpu_temp) FROM telemetry "
            "WHERE node = ? AND ts >= ? AND ts <= ? "
            "AND cpu_temp IS NOT NULL",
            (node, t_from, t_to),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])
    finally:
        conn.close()


def has_power_samples(
    db_path: str, node: str, t_from: float, t_to: float,
) -> bool:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM telemetry "
            "WHERE node = ? AND ts >= ? AND ts <= ? "
            "AND power_w IS NOT NULL",
            (node, t_from - 4.0, t_to + 4.0),
        ).fetchone()
        return bool(row and row[0] >= 2)
    finally:
        conn.close()


def probe_temp_via_agent(agent_exe: str) -> float | None:
    """Fallback: NodeAgent.exe --test-sensors (cần Administrator)."""
    try:
        proc = subprocess.run(
            [agent_exe, "--test-sensors"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # Tìm số nhiệt trong stdout kiểu "CPU Temp: 45.2" hoặc tương tự
    for line in (proc.stdout or "").splitlines():
        low = line.lower()
        if "temp" in low or "nhiệt" in low:
            for part in line.replace(",", " ").split():
                try:
                    val = float(part.strip("°C"))
                    if 20.0 <= val <= 120.0:
                        return val
                except ValueError:
                    continue
    return None


def write_jobs_csv(path: str, jobs: list[dict]) -> None:
    import csv
    fields = [
        "job_id", "node", "start_ts", "end_ts",
        "tokens_out", "scheduler_mode",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for j in jobs:
            w.writerow({k: j.get(k, "") for k in fields})


def run_energy_per_token(
    script_path: str, db_path: str, jobs_csv: str, out_json: str,
) -> dict | None:
    """Gọi energy_per_token.py; trả dict JSON hoặc None nếu thất bại."""
    import json
    import sys
    cmd = [
        sys.executable, script_path,
        "--db", db_path,
        "--jobs", jobs_csv,
        "--out", out_json,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e), "j_per_token": None}
    if proc.returncode != 0:
        return {
            "error": (proc.stderr or proc.stdout or "ept failed")[:500],
            "j_per_token": None,
            "returncode": proc.returncode,
        }
    try:
        with open(out_json, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e), "j_per_token": None}


def machine_info() -> dict:
    import os
    import platform
    import socket
    cores = os.cpu_count() or 1
    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": cores,
        "threads_used": max(1, cores - 2),
        "python": platform.python_version(),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "limitation": (
            "Đo trên 1 máy — không ngoại suy sang máy dị chủng khác trong cụm."
        ),
    }
