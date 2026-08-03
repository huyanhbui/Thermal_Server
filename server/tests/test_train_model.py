import time

from store import TelemetryStore
from train_model import build_dataset

def test_build_dataset_labels_are_delta_t():
    s = TelemetryStore(":memory:")
    # 20 min of samples every 10s: temp ramps 40→80 linearly (+2°C/min)
    for i in range(121):
        ts = i * 10.0
        s.insert("Node-A", ts, 40.0 + 2.0 * ts / 60.0, None, 50.0, 30.0)
    X, y, meta = build_dataset(s, horizon_s=180.0, window_s=180.0)
    assert len(X) == len(y) == len(meta) > 0
    assert len(X[0]) == 10
    # Rising ramp: ΔT over 3 min ≈ 2°C/min * 3 = 6°C
    assert abs(y[0] - 6.0) < 0.5

def test_build_dataset_empty_store():
    X, y, meta = build_dataset(TelemetryStore(":memory:"))
    assert X == [] and y == [] and meta == []

def test_build_dataset_is_linear_time_on_large_node():
    # O(n²) on ~5k rows would take many seconds; O(n) finishes quickly.
    s = TelemetryStore(":memory:")
    n = 5000
    for i in range(n):
        ts = float(i)
        s.insert("Node-A", ts, 40.0 + (i % 50) * 0.1, None, 50.0, 30.0)
    t0 = time.perf_counter()
    X, y, meta = build_dataset(s, horizon_s=180.0, window_s=180.0)
    elapsed = time.perf_counter() - t0
    assert len(X) == len(y) == len(meta) > 0
    assert elapsed < 2.0, f"build_dataset too slow ({elapsed:.2f}s) — still O(n²)?"
