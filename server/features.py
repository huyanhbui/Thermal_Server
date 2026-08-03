"""Turns a window of raw telemetry samples into the model's feature vector.

Ten features (ADR-004 / docs/05): six PoC baselines plus temp_above_idle,
util_slope, temp_std, fan_rpm_norm. Never include site_id, node name, or
any machine identity — that turns a shared model into a memorizer.
"""
import numpy as np

FEATURE_NAMES = [
    "cpu_temp", "mean_temp", "slope_c_per_min",
    "cpu_util", "mean_util", "power_w",
    "temp_above_idle", "util_slope", "temp_std", "fan_rpm_norm",
]

MIN_SAMPLES = 5
MIN_SPAN_S = 30.0
# Fan tach often missing on desktops; 0 means "unknown / no signal".
FAN_RPM_REF = 3000.0


def build_features(samples, idle_baseline: float = 40.0):
    usable = [s for s in samples if s.get("cpu_temp") is not None]
    if len(usable) < MIN_SAMPLES:
        return None
    ts = np.array([s["ts"] for s in usable], dtype=float)
    if ts[-1] - ts[0] < MIN_SPAN_S:
        return None
    temps = np.array([s["cpu_temp"] for s in usable], dtype=float)
    utils = np.array([s["cpu_util"] if s["cpu_util"] is not None else 0.0
                      for s in usable], dtype=float)
    powers = np.array([s["power_w"] if s["power_w"] is not None else 0.0
                       for s in usable], dtype=float)
    minutes = (ts - ts[0]) / 60.0
    slope = float(np.polyfit(minutes, temps, 1)[0])  # °C per minute
    util_slope = float(np.polyfit(minutes, utils, 1)[0])
    temp_std = float(temps.std())
    fans = [s.get("fan_rpm") for s in usable if s.get("fan_rpm") is not None]
    if fans:
        fan_norm = float(min(max(fans[-1] / FAN_RPM_REF, 0.0), 1.0))
    else:
        fan_norm = 0.0
    current = float(temps[-1])
    return [
        current,
        float(temps.mean()),
        slope,
        float(utils[-1]),
        float(utils.mean()),
        float(powers[-1]),
        current - float(idle_baseline),
        util_slope,
        temp_std,
        fan_norm,
    ]
