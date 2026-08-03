"""Báo cáo 3 phép thử ΔT trên dữ liệu tổng hợp đa node (docs/05).

Dữ liệu có trễ nhiệt phi tuyến (util burst → temp lag) để RF có tín hiệu
học được; ramp thuần tuyến tính sẽ luôn ủng hộ baseline đường thẳng.
"""
import numpy as np

from store import TelemetryStore
from train_model import (
    build_dataset, eval_buffered_time_split, eval_leave_one_node_out,
)


def _fill_node(store, name, *, baseline, gain, n=500, dt=10.0):
    """Idle baseline khác nhau + đáp ứng nhiệt bậc một theo util."""
    rng = np.random.default_rng(abs(hash(name)) % (2**31))
    temp = float(baseline)
    for i in range(n):
        ts = i * dt
        # Bursty load — shared pattern shape, different gain/baseline per node
        util = 15.0 + 70.0 * max(0.0, np.sin(i / 11.0)) ** 2
        if (i // 40) % 3 == 0:
            util = min(100.0, util + 25.0)
        # First-order lag toward util-driven target
        target = baseline + gain * (util / 100.0) * 28.0
        temp = temp + 0.18 * (target - temp) + float(rng.normal(0, 0.15))
        store.insert(name, ts, temp, None, util, 18.0 + util * 0.35)


def test_delta_t_eval_rf_beats_linear_and_reports_three_splits(capsys):
    s = TelemetryStore(":memory:")
    _fill_node(s, "thin-laptop", baseline=52.0, gain=1.35)
    _fill_node(s, "desktop", baseline=32.0, gain=0.85)
    _fill_node(s, "workstation", baseline=40.0, gain=1.05)

    X, y, meta = build_dataset(s)
    assert len(X) > 50
    assert len(X[0]) == 10

    buf = eval_buffered_time_split(X, y, meta)
    lono = eval_leave_one_node_out(X, y, meta)
    assert buf is not None, "buffered time-split cần đủ mẫu"
    assert lono is not None, "leave-one-node-out cần ≥2 node"

    print("\n=== G4 forecast eval (synthetic, non-linear lag) ===")
    print(f"(a) buffered time-split: RF={buf['rf_mae']:.3f} "
          f"Linear={buf['linear_mae']:.3f} "
          f"n_train={buf['n_train']} n_test={buf['n_test']}")
    print(f"(b) leave-one-node-out mean: RF={lono['rf_mae_mean']:.3f} "
          f"Linear={lono['linear_mae_mean']:.3f}")
    for r in lono["per_node"]:
        print(f"    holdout={r['holdout']}: RF={r['rf_mae']:.3f} "
              f"Linear={r['linear_mae']:.3f}")
    better = buf["rf_mae"] < buf["linear_mae"]
    print(f"(c) RF vs linear on buffered test: "
          f"{'RF better' if better else 'RF NOT better'}")

    # Gate cứng: RF phải hơn rõ mốc tuyến tính trên time-split có đệm.
    assert buf["rf_mae"] < buf["linear_mae"] * 0.95, (
        f"RF không hơn rõ mốc tuyến tính "
        f"(RF {buf['rf_mae']:.3f} vs Linear {buf['linear_mae']:.3f})")

    # LONO: nếu tệ hơn hẳn time-split → báo (không fail suite trên synthetic;
    # quyết định model theo node cần số đo thật / calib).
    lono_ratio = lono["rf_mae_mean"] / max(buf["rf_mae"], 1e-6)
    if lono_ratio > 2.0:
        print(f"CẢNH BÁO LONO: RF LONO/time = {lono_ratio:.2f}× — "
              f"xem xét model theo node khi có dữ liệu calib thật.")
    # RF LONO không được tệ hơn linear LONO một cách rõ rệt trên synthetic này
    assert lono["rf_mae_mean"] <= lono["linear_mae_mean"] * 1.15, (
        f"LONO: RF không hơn/gần bằng linear "
        f"(RF {lono['rf_mae_mean']:.3f} vs Linear {lono['linear_mae_mean']:.3f})")
