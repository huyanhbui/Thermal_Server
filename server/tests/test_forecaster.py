import joblib
import numpy as np
from forecaster import Forecaster

def mk_ramp(slope_per_min, n=10, start=50.0):
    # samples every 10s
    return [{"ts": t * 10.0, "cpu_temp": start + slope_per_min * (t * 10.0) / 60.0,
             "gpu_temp": None, "cpu_util": 50.0, "power_w": 30.0}
            for t in range(n)]

def test_no_model_uses_linear_fallback(tmp_path):
    f = Forecaster(model_path=str(tmp_path / "missing.pkl"))
    assert f.model_loaded is False
    samples = mk_ramp(slope_per_min=4.0)       # current = 56.0 after 90s
    pred = f.predict_max_temp(samples)
    assert abs(pred - (56.0 + 4.0 * 3.0)) < 0.1   # +12°C over 3 min
    assert abs(f.predict_delta_t(samples) - 12.0) < 0.1

def test_fallback_ignores_cooling_slope_and_caps(tmp_path):
    f = Forecaster(model_path=str(tmp_path / "missing.pkl"))
    cooling = mk_ramp(slope_per_min=-5.0)
    assert abs(f.predict_max_temp(cooling) - cooling[-1]["cpu_temp"]) < 0.1
    steep = mk_ramp(slope_per_min=50.0)
    assert f.predict_max_temp(steep) <= steep[-1]["cpu_temp"] + 20.0 + 1e-6

def test_returns_none_without_enough_history(tmp_path):
    f = Forecaster(model_path=str(tmp_path / "missing.pkl"))
    assert f.predict_max_temp(mk_ramp(1.0, n=2)) is None

def test_loads_sklearn_model_as_delta_t(tmp_path):
    """Trained model predicts ΔT; predicted_max = current + ΔT."""
    from sklearn.dummy import DummyRegressor
    model = DummyRegressor(strategy="constant", constant=5.0)
    model.fit(np.zeros((2, 10)), [5.0, 5.0])
    path = str(tmp_path / "model.pkl")
    joblib.dump(model, path)
    f = Forecaster(model_path=path)
    assert f.model_loaded is True
    samples = mk_ramp(1.0)
    cur = samples[-1]["cpu_temp"]
    assert abs(f.predict_delta_t(samples) - 5.0) < 1e-6
    assert abs(f.predict_max_temp(samples) - (cur + 5.0)) < 1e-6
