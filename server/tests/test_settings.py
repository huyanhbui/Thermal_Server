import pytest
from settings import Settings, DEFAULTS

def test_defaults_when_no_file(tmp_path):
    s = Settings(str(tmp_path / "settings.json"))
    got = s.get()
    assert got["threshold_c"] == 75.0
    assert got["scheduler_mode"] == "thermal_aware"
    assert got["model_id"] == "qwen2.5-0.5b-instruct-q4_k_m"
    assert abs(got["w_cool"] + got["w_idle"] + got["w_power"] + got["w_load"]
               - 1.0) < 1e-9

def test_set_persists_and_reloads(tmp_path):
    p = str(tmp_path / "settings.json")
    Settings(p).set_threshold(80.0)
    assert Settings(p).get()["threshold_c"] == 80.0

def test_rejects_out_of_range():
    s = Settings(":memory-not-used:.json")
    with pytest.raises(ValueError):
        s.set_threshold(30.0)
    with pytest.raises(ValueError):
        s.set_threshold(101.0)

def test_scheduler_mode_and_weights(tmp_path):
    p = str(tmp_path / "settings.json")
    s = Settings(p)
    s.set_scheduler_mode("round_robin")
    assert Settings(p).get()["scheduler_mode"] == "round_robin"
    with pytest.raises(ValueError):
        s.set_weights(0.5, 0.5, 0.5, 0.5)
    s.set_weights(0.4, 0.3, 0.2, 0.1)
    assert Settings(p).weights()["cool"] == 0.4
