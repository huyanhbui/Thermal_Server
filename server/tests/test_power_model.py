"""power_model — đường dự phòng (docs/08 §8)."""
import json

from power_model import load_power_model, apply_leakage_to_esg_config


def test_load_missing_returns_none(tmp_path):
    assert load_power_model(str(tmp_path / "nope.json")) is None


def test_estimate_and_leakage_into_esg(tmp_path):
    p = tmp_path / "power_model.json"
    p.write_text(json.dumps({
        "coefficients": {"a": 10.0, "b": 0.5, "c": 0.2},
        "temp_term_used": True,
        "leakage_w_per_c": 0.2,
        "p_idle_w": 10.0,
        "p_max_w": 60.0,
    }), encoding="utf-8")
    pm = load_power_model(str(p))
    assert pm is not None
    w = pm.estimate_w(50.0, 40.0)
    assert abs(w - (10 + 0.5 * 50 + 0.2 * 40)) < 1e-9
    cfg = {"leakage_w_per_c": None}
    apply_leakage_to_esg_config(cfg, pm)
    assert cfg["leakage_w_per_c"] == 0.2
