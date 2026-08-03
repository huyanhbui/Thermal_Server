"""Thời tiết theo site — cache, hết hạn 6h, API hỏng vẫn chạy (G6 / M12)."""
from __future__ import annotations

import json
import os

os.environ["POC_NO_BACKGROUND"] = "1"

from esg import cooling_factor, compute_report
from weather import (
    CACHE_MAX_AGE_S,
    WeatherService,
    load_weather_config,
)


def _cfg(tmp_path, **extra):
    raw = {
        "provider": "openweathermap",
        "default_site_id": "hanoi-office-4f",
        "sites": {
            "hanoi-office-4f": {
                "lat": 21.0285, "lon": 105.8542, "label": "Hà Nội",
            },
        },
        **extra,
    }
    p = tmp_path / "weather_local.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return str(p)


def test_load_config_without_file_is_disabled(tmp_path):
    cfg = load_weather_config(str(tmp_path / "missing.json"))
    assert cfg["enabled"] is False
    assert cfg["api_key"] is None


def test_load_config_with_key(tmp_path):
    path = _cfg(tmp_path, api_key="secret-test-key")
    cfg = load_weather_config(path)
    assert cfg["enabled"] is True
    assert cfg["api_key"] == "secret-test-key"
    assert "hanoi-office-4f" in cfg["sites"]


def test_fresh_fetch_cached_and_returned(tmp_path):
    calls = []

    def fetch(site, cfg, now):
        calls.append(now)
        return {"temp_c": 34.0, "feels_like_c": 41.0}

    svc = WeatherService(
        config_path=_cfg(tmp_path, api_key="k"),
        fetch_fn=fetch,
    )
    got = svc.get("hanoi-office-4f", now=1000.0)
    assert got is not None
    assert got["temp_c"] == 34.0
    assert got["feels_like_c"] == 41.0
    assert got["updated_at"] == 1000.0
    assert got["source"] == "api"
    assert len(calls) == 1

    # Trong TTL fetch: đọc cache, không gọi lại API
    got2 = svc.get("hanoi-office-4f", now=1000.0 + 60.0)
    assert got2["temp_c"] == 34.0
    assert got2["source"] == "cache"
    assert len(calls) == 1


def test_stale_cache_over_6h_is_ignored(tmp_path):
    def fetch(site, cfg, now):
        return {"temp_c": 30.0, "feels_like_c": 32.0}

    svc = WeatherService(
        config_path=_cfg(tmp_path, api_key="k"),
        fetch_fn=fetch,
    )
    assert svc.get("hanoi-office-4f", now=0.0)["temp_c"] == 30.0

    # API hỏng sau khi cache đã > 6 giờ → bỏ qua, không dùng số cũ
    def boom(site, cfg, now):
        raise RuntimeError("network down")

    svc._fetch_fn = boom
    got = svc.get("hanoi-office-4f", now=CACHE_MAX_AGE_S + 1.0)
    assert got is None


def test_api_fail_uses_fresh_cache(tmp_path):
    n = {"i": 0}

    def fetch(site, cfg, now):
        n["i"] += 1
        if n["i"] == 1:
            return {"temp_c": 28.0, "feels_like_c": 30.0}
        raise RuntimeError("timeout")

    svc = WeatherService(
        config_path=_cfg(tmp_path, api_key="k"),
        fetch_fn=fetch,
        fetch_interval_s=0.0,  # luôn thử refresh
    )
    assert svc.get("hanoi-office-4f", now=100.0)["temp_c"] == 28.0
    # Cache còn mới (<6h), API hỏng → dùng cache
    got = svc.get("hanoi-office-4f", now=200.0)
    assert got is not None
    assert got["temp_c"] == 28.0
    assert got["source"] == "cache"


def test_no_api_key_returns_none(tmp_path):
    svc = WeatherService(config_path=_cfg(tmp_path))  # không api_key
    assert svc.get("hanoi-office-4f", now=1.0) is None


def test_snapshot_for_dashboard(tmp_path):
    svc = WeatherService(
        config_path=_cfg(tmp_path, api_key="k"),
        fetch_fn=lambda *a, **k: {"temp_c": 33.0, "feels_like_c": 38.0},
    )
    svc.refresh("hanoi-office-4f", 50.0)
    snap = svc.snapshot(now=60.0)
    assert "hanoi-office-4f" in snap
    assert snap["hanoi-office-4f"]["temp_c"] == 33.0
    assert snap["hanoi-office-4f"]["label"] == "Hà Nội"


def test_cooling_factor_uses_outdoor_temp():
    base = cooling_factor({"cooling_base_factor": 0.25,
                            "cooling_weather_k": 0.02,
                            "cooling_reference_temp_c": 25.0,
                            "outdoor_temp_c": None})
    assert abs(base - 0.25) < 1e-9
    hot = cooling_factor({"cooling_base_factor": 0.25,
                           "cooling_weather_k": 0.02,
                           "cooling_reference_temp_c": 25.0,
                           "outdoor_temp_c": 35.0})
    # 0.25 × (1 + 0.02 × 10) = 0.30
    assert abs(hot - 0.30) < 1e-9


def test_esg_tier2_includes_weather_assumption():
    events = [{
        "ts": 1.0, "node": "A", "event_type": "job_completed",
        "detail": {
            "status": "ok", "energy_source": "model",
            "energy_j": 100.0, "tokens_out": 10,
            "scheduler_mode": "thermal_aware",
            "delta_t_avoided_c": 5.0, "duration_h": 1.0,
        },
    }]
    r = compute_report(events, {
        "leakage_w_per_c": 0.18,
        "outdoor_temp_c": 34.0,
        "cooling_base_factor": 0.25,
        "cooling_weather_k": 0.02,
        "cooling_reference_temp_c": 25.0,
    })
    assump = " ".join(r["tier2_derived"]["assumptions"])
    assert "34" in assump or "T ngoài" in assump
    assert r["tier2_derived"]["cooling_factor"] > 0.25


def test_apply_outdoor_to_esg_config(tmp_path):
    from weather import apply_weather_to_esg

    svc = WeatherService(
        config_path=_cfg(tmp_path, api_key="k"),
        fetch_fn=lambda *a, **k: {"temp_c": 36.0, "feels_like_c": 40.0},
    )
    cfg = {"outdoor_temp_c": None, "cooling_base_factor": 0.25}
    svc.refresh("hanoi-office-4f", 10.0)
    apply_weather_to_esg(svc, cfg, site_id="hanoi-office-4f", now=10.0)
    assert cfg["outdoor_temp_c"] == 36.0

    # Hết hạn 6h + API chết → xóa outdoor (không giữ số cũ)
    def boom(*a, **k):
        raise RuntimeError("down")

    svc._fetch_fn = boom
    apply_weather_to_esg(
        svc, cfg, site_id="hanoi-office-4f",
        now=CACHE_MAX_AGE_S + 20.0)
    assert cfg["outdoor_temp_c"] is None
