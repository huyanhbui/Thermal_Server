"""Builds a supervised dataset from recorded telemetry and trains the
Random Forest forecaster. Label = ΔT = max(CPU temp over next 3 min)
minus current temp (ADR-004).

Usage (dev, CWD = server/):
    python train_model.py
    python train_model.py --eval

Packaged Host (THERMAL_DATA_DIR set, e.g. ProgramData\\...\\shared):
    set THERMAL_DATA_DIR=%ProgramData%\\ThermalOrchestrator\\shared
    python train_model.py
    # writes model.pkl next to telemetry.db in that data dir — same place
    # make_state / Forecaster load after restart.

Override paths anytime: --db PATH --out PATH
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from features import build_features
from forecast_cache import idle_baseline_from_samples
from store import TelemetryStore

HORIZON_S = 180.0
WINDOW_S = 180.0


def _default_db_path() -> str:
    data_dir = (os.environ.get("THERMAL_DATA_DIR") or "").strip()
    if data_dir:
        return os.path.join(data_dir, "telemetry.db")
    return "telemetry.db"


def _default_model_path() -> str:
    data_dir = (os.environ.get("THERMAL_DATA_DIR") or "").strip()
    if data_dir:
        return os.path.join(data_dir, "model.pkl")
    return "model.pkl"


def build_dataset(store, horizon_s=HORIZON_S, window_s=WINDOW_S,
                  idle_baseline: float | None = None):
    """Two sliding pointers per node — O(n), not O(n²).

    Labels are ΔT (°C), not absolute max temp.
    """
    X, y = [], []
    meta = []  # (node, ts) for eval splits
    for node in store.nodes():
        rows = [r for r in store.all_rows(node) if r["cpu_temp"] is not None]
        if not rows:
            continue
        if idle_baseline is not None:
            baseline = idle_baseline
        else:
            baseline = idle_baseline_from_samples(rows, fallback=40.0)
        lo = hi = 0
        for i, row in enumerate(rows):
            t = row["ts"]
            while lo < i and rows[lo]["ts"] < t - window_s:
                lo += 1
            while hi < len(rows) and rows[hi]["ts"] <= t + horizon_s:
                hi += 1
            # Need the full horizon ahead; later rows only have less future.
            if rows[-1]["ts"] < t + horizon_s:
                break
            future = rows[i + 1:hi]
            if not future:
                continue
            feats = build_features(rows[lo:i + 1], idle_baseline=baseline)
            if feats is None:
                continue
            X.append(feats)
            y.append(max(r["cpu_temp"] for r in future) - row["cpu_temp"])
            meta.append((node, t))
    return X, y, meta


def _linear_delta(feats):
    slope = feats[2]
    return min(max(slope, 0.0) * 3.0, 20.0)


def _mae(y_true, y_pred):
    if len(y_true) == 0:
        return float("nan")
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def eval_buffered_time_split(X, y, meta, horizon_s=HORIZON_S):
    """Time split with horizon buffer at the 80% cutoff (docs/05)."""
    from sklearn.ensemble import RandomForestRegressor

    if len(X) < 20:
        return None
    order = np.argsort([m[1] for m in meta])
    Xa = np.asarray(X)[order]
    ya = np.asarray(y)[order]
    ts = np.asarray([meta[i][1] for i in order])
    cut_idx = int(len(Xa) * 0.8)
    if cut_idx < 5 or cut_idx >= len(Xa):
        return None
    t_cut = ts[cut_idx]
    # Drop train samples whose label window crosses the cut.
    train_mask = ts[:cut_idx] + horizon_s <= t_cut
    # Drop test samples whose feature window overlaps train side.
    test_mask = ts[cut_idx:] >= t_cut + horizon_s
    X_tr, y_tr = Xa[:cut_idx][train_mask], ya[:cut_idx][train_mask]
    X_te, y_te = Xa[cut_idx:][test_mask], ya[cut_idx:][test_mask]
    if len(X_tr) < 10 or len(X_te) < 5:
        # Fall back to simple 80/20 without buffer if too sparse.
        X_tr, y_tr = Xa[:cut_idx], ya[:cut_idx]
        X_te, y_te = Xa[cut_idx:], ya[cut_idx:]
    model = RandomForestRegressor(
        n_estimators=200, max_depth=12, min_samples_leaf=5,
        random_state=42, n_jobs=1)
    model.fit(X_tr, y_tr)
    rf_mae = _mae(y_te, model.predict(X_te))
    lin_mae = _mae(y_te, [_linear_delta(f) for f in X_te])
    return {
        "n_train": len(X_tr), "n_test": len(X_te),
        "rf_mae": rf_mae, "linear_mae": lin_mae,
    }


def eval_leave_one_node_out(X, y, meta):
    """Train on all-but-one node; test on held-out node. Decisive for S4."""
    from sklearn.ensemble import RandomForestRegressor

    nodes = sorted({m[0] for m in meta})
    if len(nodes) < 2:
        return None
    Xa, ya = np.asarray(X), np.asarray(y)
    rows = []
    rf_errs, lin_errs = [], []
    for hold in nodes:
        tr = [i for i, m in enumerate(meta) if m[0] != hold]
        te = [i for i, m in enumerate(meta) if m[0] == hold]
        if len(tr) < 10 or len(te) < 5:
            continue
        model = RandomForestRegressor(
            n_estimators=200, max_depth=12, min_samples_leaf=5,
            random_state=42, n_jobs=1)
        model.fit(Xa[tr], ya[tr])
        pred = model.predict(Xa[te])
        rf = _mae(ya[te], pred)
        lin = _mae(ya[te], [_linear_delta(f) for f in Xa[te]])
        rows.append({"holdout": hold, "n_test": len(te),
                     "rf_mae": rf, "linear_mae": lin})
        rf_errs.append(rf)
        lin_errs.append(lin)
    if not rows:
        return None
    return {
        "per_node": rows,
        "rf_mae_mean": float(np.mean(rf_errs)),
        "linear_mae_mean": float(np.mean(lin_errs)),
    }


def run_eval(store):
    X, y, meta = build_dataset(store)
    print(f"[EVAL] dataset: {len(X)} samples, nodes={store.nodes()}")
    if len(X) < 20:
        print("[EVAL] Not enough data for eval (<20).")
        return 1
    buf = eval_buffered_time_split(X, y, meta)
    lono = eval_leave_one_node_out(X, y, meta)
    # (c) Overall linear vs RF on same buffered test if available
    print("--- (a) Chia theo thời gian CÓ ĐỆM ---")
    if buf:
        print(f"  n_train={buf['n_train']} n_test={buf['n_test']}")
        print(f"  RF MAE ΔT:     {buf['rf_mae']:.3f} °C")
        print(f"  Linear MAE ΔT: {buf['linear_mae']:.3f} °C")
        if buf["rf_mae"] >= buf["linear_mae"] * 0.95:
            print("  CẢNH BÁO: RF không hơn rõ mốc tuyến tính.")
    else:
        print("  (không đủ dữ liệu)")
    print("--- (b) Leave-one-node-out (phép thử quyết định) ---")
    if lono:
        for r in lono["per_node"]:
            print(f"  holdout={r['holdout']}: RF={r['rf_mae']:.3f} "
                  f"Linear={r['linear_mae']:.3f} n={r['n_test']}")
        print(f"  mean RF MAE:     {lono['rf_mae_mean']:.3f} °C")
        print(f"  mean Linear MAE: {lono['linear_mae_mean']:.3f} °C")
        if buf and lono["rf_mae_mean"] > buf["rf_mae"] * 1.5:
            print("  CẢNH BÁO: LONO tệ hơn hẳn time-split — "
                  "có thể cần model theo node.")
    else:
        print("  (cần ≥2 node có đủ mẫu)")
    print("--- (c) Mốc so sánh tuyến tính ---")
    if buf:
        better = buf["rf_mae"] < buf["linear_mae"]
        print(f"  RF {'HƠN' if better else 'KHÔNG HƠN'} đường thẳng "
              f"(RF {buf['rf_mae']:.3f} vs Linear {buf['linear_mae']:.3f})")
    return 0


def train_and_save(store, out_path: str | None = None):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error
    import joblib

    if out_path is None:
        out_path = _default_model_path()
    X, y, _meta = build_dataset(store)
    print(f"[TRAIN] dataset: {len(X)} samples from nodes {store.nodes()}")
    if len(X) < 100:
        raise SystemExit(
            "[TRAIN] Not enough data (<100 rows). "
            "Run 'python server.py --calibrate' first (~20 min).")
    X, y = np.array(X), np.array(y)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, shuffle=False)
    model = RandomForestRegressor(
        n_estimators=200, max_depth=12, min_samples_leaf=5,
        random_state=42, n_jobs=-1)
    model.fit(X_tr, y_tr)
    mae = mean_absolute_error(y_te, model.predict(X_te))
    lin_mae = mean_absolute_error(
        y_te, [_linear_delta(f) for f in X_te])
    print(f"[TRAIN] validation MAE ΔT: {mae:.2f}°C "
          f"(linear baseline {lin_mae:.2f}°C)")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    joblib.dump(model, out_path)
    print(f"[TRAIN] saved {out_path} - restart server.py to use it")
    if mae >= lin_mae * 0.95:
        print("[TRAIN] CẢNH BÁO: RF không hơn rõ mốc tuyến tính.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true",
                    help="Báo cáo 3 phép thử (không ghi model.pkl)")
    ap.add_argument("--db", default=None,
                    help="Telemetry SQLite (default: data dir or ./telemetry.db)")
    ap.add_argument("--out", default=None,
                    help="Output model.pkl (default: data dir or ./model.pkl)")
    args = ap.parse_args()
    db_path = args.db or _default_db_path()
    store = TelemetryStore(db_path)
    if args.eval:
        raise SystemExit(run_eval(store))
    train_and_save(store, out_path=args.out or _default_model_path())
