"""ESG ba tầng — E1–E14 + X5 (docs/11 §7)."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from esg import TIER3_LABEL, compute_report
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    create_app, make_state, run_forecast_cycle)
from store import TelemetryStore


def _state(tmp_path, **kw):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "m.pkl"),
                      settings_path=str(tmp_path / "s.json"),
                      esg_path=str(tmp_path / "e.json"),
                      **kw)


def _ev(ts, node, etype, detail):
    return {"ts": ts, "node": node, "event_type": etype, "detail": detail}


def _sensor(ts, node, energy_j, tokens, mode="thermal_aware", **extra):
    d = {"status": "ok", "energy_source": "sensor",
         "energy_j": energy_j, "tokens_out": tokens,
         "scheduler_mode": mode, **extra}
    return _ev(ts, node, "job_completed", d)


def test_e1_sensor_jobs_enter_tier1():
    events = [
        _sensor(1, "A", 100.0, 50),
        _ev(2, "A", "job_completed", {
            "status": "ok", "energy_source": "none",
            "tokens_out": 10, "scheduler_mode": "thermal_aware",
        }),
    ]
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 1
    assert abs(r["tier1_measured"]["j_per_token"] - 2.0) < 1e-9


def test_e2_model_jobs_enter_tier2_not_tier1():
    events = [
        _ev(1, "A", "job_completed", {
            "status": "ok", "energy_source": "model",
            "energy_j": 200.0, "tokens_out": 50,
            "scheduler_mode": "thermal_aware",
            "delta_t_avoided_c": 5.0, "duration_h": 1.0,
        }),
    ]
    r = compute_report(events, {"leakage_w_per_c": 0.18})
    assert r["tier1_measured"]["samples"] == 0
    assert r["tier1_measured"]["j_per_token"] is None
    assert r["tier2_derived"]["kwh_leakage_saved"] > 0


def test_e3_none_source_enters_no_tier():
    events = [
        _ev(1, "A", "job_completed", {
            "status": "ok", "energy_source": "none",
            "tokens_out": 100, "scheduler_mode": "thermal_aware",
            "delta_t_avoided_c": 10.0, "duration_h": 1.0,
        }),
    ]
    r = compute_report(events, {"leakage_w_per_c": 0.18})
    assert r["tier1_measured"]["samples"] == 0
    assert r["tier2_derived"]["kwh_leakage_saved"] == 0.0


def test_e4_mixed_sensor_nodes_only_count_sensor_machines():
    # 3 máy sensor + 2 không
    events = [
        _sensor(1, "S1", 30.0, 10),
        _sensor(2, "S2", 30.0, 10),
        _sensor(3, "S3", 30.0, 10),
        _ev(4, "N1", "job_completed", {
            "status": "ok", "energy_source": "none", "tokens_out": 99,
            "scheduler_mode": "thermal_aware"}),
        _ev(5, "N2", "job_completed", {
            "status": "ok", "energy_source": "none", "tokens_out": 99,
            "scheduler_mode": "thermal_aware"}),
    ]
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 3
    assert set(r["tier1_measured"]["sensor_nodes"]) == {"S1", "S2", "S3"}
    assert abs(r["tier1_measured"]["j_per_token"] - 3.0) < 1e-9


def test_e5_under_20_samples_hides_improvement_pct():
    events = []
    for i in range(10):
        events.append(_sensor(i, "A", 10.0, 5, mode="round_robin"))
        events.append(_sensor(100 + i, "A", 8.0, 5, mode="thermal_aware"))
    # 20 total sensor but... wait E5 is under 20. Use 19.
    events = events[:19]
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 19
    assert r["tier1_measured"]["improvement_pct"] is None
    assert r["tier1_measured"]["confidence"] == "chưa đủ dữ liệu"


def test_e6_exactly_20_shows_preliminary():
    events = []
    for i in range(10):
        events.append(_sensor(i, "A", 10.0, 5, mode="round_robin"))
        events.append(_sensor(100 + i, "A", 8.0, 5, mode="thermal_aware"))
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 20
    assert r["tier1_measured"]["improvement_pct"] is not None
    assert r["tier1_measured"]["confidence"] == "sơ bộ"


def test_e7_100_samples_ok_label():
    events = []
    for i in range(50):
        events.append(_sensor(i, "A", 10.0, 5, mode="round_robin"))
        events.append(_sensor(1000 + i, "A", 8.0, 5, mode="thermal_aware"))
    r = compute_report(events)
    assert r["tier1_measured"]["samples"] == 100
    assert r["tier1_measured"]["confidence"] == "ok"


def test_e8_negative_improvement_kept():
    # thermal tệ hơn RR → âm
    events = [
        _sensor(1, "A", 50.0, 50, mode="round_robin"),
        _sensor(2, "A", 100.0, 50, mode="thermal_aware"),
    ]
    # samples=2 < 20 → improvement hidden. Force show via config.
    r = compute_report(events, {"min_samples_to_show": 1})
    assert r["tier1_measured"]["improvement_pct"] is not None
    assert r["tier1_measured"]["improvement_pct"] < 0


def test_e9_threshold_change_splits_segments():
    events = [
        _sensor(1, "A", 100.0, 50, mode="thermal_aware",
                threshold_at_time=75.0),
        _ev(10, "system", "threshold_changed",
            {"old": 75.0, "new": 80.0, "threshold_at_time": 80.0}),
        _sensor(20, "A", 80.0, 40, mode="thermal_aware",
                threshold_at_time=80.0),
    ]
    r = compute_report(events)
    assert "segments" in r
    assert len(r["segments"]) >= 2
    # Top-level = khoảng mới nhất (80°C)
    assert r["segments"][-1]["threshold_c"] == 80.0
    # Không cộng gộp samples hai khoảng vào top-level cùng một phép
    assert r["tier1_measured"]["samples"] == 1


def test_e10_recompute_from_events_is_deterministic():
    events = [_sensor(1, "A", 80.0, 40)]
    a = compute_report(events, {"price_vnd_per_kwh": 2500})
    b = compute_report(events, {"price_vnd_per_kwh": 2500})
    assert a == b


def test_e11_change_constants_changes_report_not_ledger():
    events = [
        _sensor(1, "A", 100.0, 50,
                delta_t_avoided_c=5.0, duration_h=1.0),
    ]
    r1 = compute_report(events, {"leakage_w_per_c": 0.18})
    r2 = compute_report(events, {"leakage_w_per_c": 0.36})
    assert r1["tier2_derived"]["kwh_leakage_saved"] != \
        r2["tier2_derived"]["kwh_leakage_saved"]
    # Nhật ký không đổi
    assert events[0]["detail"]["energy_j"] == 100.0


def test_e12_threshold_below_idle_baseline_rejected(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    for i in range(10):
        state.store.insert("Node-A", 100.0 - 90 + i * 10, 45.0, None, 5.0, 15.0)
    run_forecast_cycle(state, 100.0)
    admin = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD, "role": "admin",
    }).json()["token"]
    r = c.post("/api/settings",
               headers={"Authorization": f"Bearer {admin}"},
               json={"threshold_c": 40})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "THRESHOLD_TOO_LOW"


def test_e13_flagging_all_nodes_does_not_improve_j_per_token():
    base = [_sensor(1, "A", 100.0, 50)]
    flagged = base + [
        _ev(2, "A", "flagged", {"pred": 90}),
        _ev(3, "B", "flagged", {"pred": 91}),
        _ev(4, "C", "flagged", {"pred": 92}),
    ]
    j0 = compute_report(base)["tier1_measured"]["j_per_token"]
    j1 = compute_report(flagged)["tier1_measured"]["j_per_token"]
    assert j0 == j1


def test_e14_three_separate_tier_objects():
    r = compute_report([])
    assert set(r.keys()) == {
        "tier1_measured", "tier2_derived", "tier3_projected"}
    assert "label_derived" in r["tier3_projected"]
    assert TIER3_LABEL in r["tier3_projected"]["label_derived"]
    assert "kwh_projected_measured" in r["tier3_projected"]
    assert "kwh_projected" not in r["tier3_projected"]
    assert "hot_hours_avoided" not in r
    assert "kwh_saved" not in r
    assert "scale_note" in r["tier3_projected"]


def test_x5_restart_recomputes_from_ledger(tmp_path):
    db = str(tmp_path / "telemetry.db")
    store = TelemetryStore(db)
    store.insert_esg_event(1.0, "A", "job_completed", {
        "status": "ok", "energy_source": "sensor",
        "energy_j": 90.0, "tokens_out": 30,
        "scheduler_mode": "thermal_aware",
        "threshold_at_time": 75.0,
    })
    r1 = compute_report(store.esg_events())
    # "Khởi động lại" — store mới cùng file
    store2 = TelemetryStore(db)
    r2 = compute_report(store2.esg_events())
    assert r1 == r2
    assert abs(r2["tier1_measured"]["j_per_token"] - 3.0) < 1e-9


def test_api_state_esg_has_three_tiers(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = c.post("/join", json={
        "room_code": DEFAULT_ROOM_CODE,
        "password": DEFAULT_ADMIN_PASSWORD, "role": "admin",
    }).json()["token"]
    esg = c.get("/api/state",
                headers={"Authorization": f"Bearer {admin}"}).json()["esg"]
    assert "tier1_measured" in esg
    assert "tier2_derived" in esg
    assert "tier3_projected" in esg


def test_ab_benchmark_runs_and_may_be_negative(tmp_path):
    from ab_benchmark import default_prompts_path, run_ab_benchmark
    # Rút gọn: 4 prompt tạm
    p = tmp_path / "p.json"
    import json
    base = json.load(open(default_prompts_path(), encoding="utf-8"))
    json.dump(base[:4], open(p, "w", encoding="utf-8"), ensure_ascii=False)
    s = run_ab_benchmark(str(p), cooldown_s=1.0)
    assert s["samples"] is not None and s["samples"] > 0
    # improvement có thể âm — chỉ cần có số hoặc None (thiếu mẫu)
    if s["improvement_pct"] is not None:
        assert isinstance(s["improvement_pct"], float)
