"""Test #5 — power_baseline.py --manual-power."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "measure_power"
sys.path.insert(0, str(SCRIPT_DIR))

import power_baseline as pb  # noqa: E402


def test_manual_power_prompted_during_load_second_half():
    """Hỏi watt giữa hai pha tải (sau SETTLE_FRACTION), không sau khi dừng hẳn."""
    call_order = []

    def track_load(util, duration, workers):
        call_order.append("load")

    def mock_input(_prompt=""):
        call_order.append("input")
        return "120"

    args = MagicMock()
    args.node = "Node-A"
    args.db = ":memory:"
    args.steps = "50"
    args.step_seconds = 100.0
    args.workers = 1
    args.manual_power = True

    with patch.object(pb, "run_load_step", side_effect=track_load), \
         patch.object(pb, "fetch_samples", return_value=[]), \
         patch.object(pb, "input", side_effect=mock_input), \
         patch.object(pb.time, "time", side_effect=[0.0, 50.0, 50.0, 100.0]):
        pb.collect_baseline(args)

    assert call_order == ["load", "input", "load"]


def test_manual_power_enter_skips_no_fake_number():
    args = MagicMock()
    args.node = "Node-A"
    args.db = ":memory:"
    args.steps = "50"
    args.step_seconds = 10.0
    args.workers = 1
    args.manual_power = True

    with patch.object(pb, "run_load_step"), \
         patch.object(pb, "fetch_samples", return_value=[
             {"ts": 5.0, "cpu_temp": 50.0, "cpu_util": 50, "power_w": None},
         ]), \
         patch.object(pb, "input", return_value=""), \
         patch.object(pb.time, "time", side_effect=[0.0, 5.0, 10.0]):
        rows = pb.collect_baseline(args)

    assert all(r["power_w"] is None for r in rows)
    assert all(r["power_source"] == "none" for r in rows)


def test_manual_power_stores_timestamp():
    args = MagicMock()
    args.node = "Node-A"
    args.db = ":memory:"
    args.steps = "50"
    args.step_seconds = 10.0
    args.workers = 1
    args.manual_power = True

    times = [0.0, 7.5, 7.5, 10.0]

    with patch.object(pb, "run_load_step"), \
         patch.object(pb, "fetch_samples", return_value=[
             {"ts": 8.0, "cpu_temp": 55.0, "cpu_util": 50, "power_w": None},
         ]), \
         patch.object(pb, "input", return_value="88.5"), \
         patch.object(pb.time, "time", side_effect=times):
        rows = pb.collect_baseline(args)

    manual_rows = [r for r in rows if r["power_source"] == "manual"]
    assert len(manual_rows) == 1
    assert manual_rows[0]["power_w"] == 88.5
    assert manual_rows[0]["power_reading_ts"] == 7.5
