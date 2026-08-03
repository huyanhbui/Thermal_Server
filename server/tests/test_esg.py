import os

from esg import (compute_report, kwh_saved, money_saved, co2_avoided_kg,
                 EsgTracker, load_esg_config, TIER3_LABEL)

CFG = {"node_power_kw": 0.1, "cooling_overhead_factor": 0.5,
       "price_usd_per_kwh": 0.10, "price_vnd_per_kwh": 2500,
       "co2_kg_per_kwh": 0.72}


def test_formulas():
    assert kwh_saved(2.0, 0.1, 0.5) == 0.1
    assert money_saved(10.0, 0.10) == 1.0
    assert abs(co2_avoided_kg(10.0, 0.72) - 7.2) < 1e-9


def test_compute_report_sensor_only_in_tier1():
    events = [{
        "ts": 1, "node": "A", "event_type": "job_completed",
        "detail": {"status": "ok", "energy_source": "sensor",
                   "energy_j": 90.0, "tokens_out": 30,
                   "scheduler_mode": "thermal_aware"},
    }]
    r = compute_report(events, CFG)
    assert abs(r["tier1_measured"]["j_per_token"] - 3.0) < 1e-9
    assert "kwh_projected_measured" in r["tier3_projected"]
    assert TIER3_LABEL in r["tier3_projected"]["label_derived"]


def test_tracker_flag_helpers_still_work():
    t = EsgTracker(CFG)
    t.node_flagged("Node-A", now=0.0)
    t.node_cleared("Node-A", now=3600.0)
    # Báo cáo từ ledger rỗng — không còn hot_hours phẳng
    r = t.report(now=3600.0, events=[])
    assert "tier1_measured" in r


def test_load_config_reads_defaults(tmp_path):
    p = tmp_path / "esg_config.json"
    p.write_text('{"node_power_kw": 0.2}', encoding="utf-8")
    cfg = load_esg_config(str(p))
    assert cfg["node_power_kw"] == 0.2
    assert cfg["co2_kg_per_kwh"] == 0.72


def test_load_nested_config_flattens_and_null_leakage(tmp_path):
    p = tmp_path / "esg_config.json"
    p.write_text("""{
      "tier1": {"min_samples_to_show": 20, "min_samples_for_confidence": 100},
      "tier2": {"leakage_w_per_c": null, "cooling_base_factor": 0.25},
      "tier3": {"price_vnd_per_kwh": 2500, "co2_kg_per_kwh": 0.72},
      "anti_gaming": {"threshold_margin_above_idle_c": 8.0},
      "legacy": {"node_power_kw": 0.065}
    }""", encoding="utf-8")
    cfg = load_esg_config(str(p))
    assert cfg["leakage_w_per_c"] is None
    assert cfg["cooling_base_factor"] == 0.25
    assert cfg["min_samples_to_show"] == 20
    assert cfg["threshold_margin_above_idle_c"] == 8.0
    assert cfg["node_power_kw"] == 0.065


def test_repo_esg_config_has_sources():
    from esg import config_sources_ok
    path = os.path.join(os.path.dirname(__file__), "..", "esg_config.json")
    missing = config_sources_ok(path)
    assert missing == [], f"thiếu _source: {missing}"
