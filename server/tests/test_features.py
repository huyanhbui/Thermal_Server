from features import build_features, FEATURE_NAMES

def mk(ts, temp, util=50.0, power=30.0, fan_rpm=None):
    row = {"ts": ts, "cpu_temp": temp, "gpu_temp": None,
           "cpu_util": util, "power_w": power}
    if fan_rpm is not None:
        row["fan_rpm"] = fan_rpm
    return row

def test_returns_none_when_too_few_samples():
    assert build_features([mk(0, 50), mk(2, 51)]) is None

def test_returns_none_when_span_too_short():
    samples = [mk(i, 50) for i in range(5)]  # 4s span
    assert build_features(samples) is None

def test_feature_values_on_linear_ramp():
    # +1°C every 10s = 6°C/min slope
    samples = [mk(t, 50 + t / 10, util=40.0, power=20.0) for t in range(0, 61, 10)]
    f = build_features(samples, idle_baseline=40.0)
    assert len(f) == len(FEATURE_NAMES) == 10
    assert f[0] == 56.0                    # current temp
    assert abs(f[1] - 53.0) < 0.01         # mean temp
    assert abs(f[2] - 6.0) < 0.01          # slope °C/min
    assert f[3] == 40.0 and f[4] == 40.0 and f[5] == 20.0
    assert abs(f[6] - 16.0) < 0.01         # temp_above_idle = 56-40
    assert abs(f[7] - 0.0) < 0.01          # util_slope flat
    assert f[8] >= 0.0                     # temp_std
    assert f[9] == 0.0                     # no fan_rpm → 0

def test_fan_rpm_norm_when_present():
    samples = [mk(t, 50.0, fan_rpm=1500) for t in range(0, 61, 10)]
    f = build_features(samples)
    assert abs(f[9] - 0.5) < 0.01  # 1500/3000

def test_skips_samples_with_null_cpu_temp_and_nulls_default_zero():
    samples = [mk(t, 50.0, util=None, power=None) for t in range(0, 61, 10)]
    samples.insert(3, {"ts": 25, "cpu_temp": None, "gpu_temp": None,
                       "cpu_util": None, "power_w": None})
    f = build_features(samples)
    assert f[0] == 50.0 and f[3] == 0.0 and f[5] == 0.0
