"""Kiểm ForecastCache không đè inflight runtime."""
from forecast_cache import ForecastCache, NodeForecast


def test_inflight_survives_forecast_put():
    """put() giữ inflight sống — tránh race với scheduler/result."""
    cache = ForecastCache()
    cache.put(NodeForecast(node="A", state="READY", inflight=0,
                           last_sample_ts=1.0))
    cache.adjust_inflight("A", 1)
    assert cache.get("A").inflight == 1
    # Forecast cycle ghi lại hàng mới với inflight=0 trong object
    cache.put(NodeForecast(node="A", state="READY", predicted_max_c=60.0,
                           inflight=0, last_sample_ts=2.0))
    assert cache.get("A").inflight == 1


def test_patch_consecutive_errors_preserves_inflight():
    cache = ForecastCache()
    cache.put(NodeForecast(node="A", state="READY", inflight=2,
                           consecutive_errors=0, last_sample_ts=1.0))
    cache.patch("A", consecutive_errors=2)
    f = cache.get("A")
    assert f.consecutive_errors == 2 and f.inflight == 2
