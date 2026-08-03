"""Thời tiết theo site — chỉ phục vụ ESG Tầng 2 và panel dashboard (G6).

KHÔNG đưa vào công thức chấm điểm scheduler (M12): nếu mọi node cùng site thì
số hạng thời tiết là hằng số và triệt tiêu trong phép so sánh. Mặc định
w_weather = 0; module này chỉ cung cấp T ngoài trời cho cooling_factor.

API key nằm trong weather_local.json (gitignore) — không commit.
Cache cũ quá 6 giờ bị BỎ QUA, không dùng số cũ.

Chạy gián tiếp qua vòng nền host hoặc WeatherService.get().
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger("weather")

CACHE_MAX_AGE_S = 6 * 3600.0
FETCH_INTERVAL_S = 15 * 60.0
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

DEFAULT_SITES = {
    "hanoi-office-4f": {
        "lat": 21.0285, "lon": 105.8542, "label": "Hà Nội",
    },
}


def load_weather_config(path: str) -> dict:
    """Đọc config cục bộ. Thiếu file / thiếu key → enabled=False."""
    cfg = {
        "enabled": False,
        "api_key": None,
        "provider": "openweathermap",
        "default_site_id": "hanoi-office-4f",
        "sites": dict(DEFAULT_SITES),
        "path": path,
    }
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("[WEATHER] không đọc được %s: %s", path, e)
        return cfg
    key = raw.get("api_key") or raw.get("openweather_api_key")
    if isinstance(key, str):
        key = key.strip() or None
    sites = raw.get("sites") or DEFAULT_SITES
    cfg.update({
        "api_key": key,
        "enabled": bool(key),
        "provider": raw.get("provider") or "openweathermap",
        "default_site_id": (
            raw.get("default_site_id") or "hanoi-office-4f"),
        "sites": dict(sites),
    })
    return cfg


def _default_fetch(site_id: str, cfg: dict, now: float) -> dict:
    """Gọi OpenWeatherMap. Trả {temp_c, feels_like_c}."""
    key = cfg.get("api_key")
    if not key:
        raise RuntimeError("missing api_key")
    site = (cfg.get("sites") or {}).get(site_id) or {}
    lat = site.get("lat")
    lon = site.get("lon")
    if lat is None or lon is None:
        raise RuntimeError(f"site {site_id} thiếu lat/lon")
    qs = urllib.parse.urlencode({
        "lat": lat, "lon": lon, "appid": key, "units": "metric",
    })
    url = f"{OWM_URL}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "ThermalPoC/1"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    main = body.get("main") or {}
    temp = main.get("temp")
    feels = main.get("feels_like", temp)
    if temp is None:
        raise RuntimeError("OWM response thiếu main.temp")
    return {"temp_c": float(temp), "feels_like_c": float(feels)}


class WeatherService:
    """Cache theo site; >6h bỏ qua; API lỗi dùng cache còn hạn."""

    def __init__(
        self,
        config_path: str = "weather_local.json",
        *,
        fetch_fn: Callable | None = None,
        fetch_interval_s: float = FETCH_INTERVAL_S,
    ):
        self.config_path = config_path
        self._fetch_fn = fetch_fn or _default_fetch
        self.fetch_interval_s = float(fetch_interval_s)
        self._cache: dict[str, dict] = {}
        self._cfg = load_weather_config(config_path)

    def reload_config(self) -> None:
        self._cfg = load_weather_config(self.config_path)

    @property
    def config(self) -> dict:
        return self._cfg

    def _try_fetch(self, site_id: str, now: float) -> dict | None:
        if not self._cfg.get("enabled"):
            return None
        try:
            raw = self._fetch_fn(site_id, self._cfg, now)
            entry = {
                "temp_c": float(raw["temp_c"]),
                "feels_like_c": float(
                    raw.get("feels_like_c", raw["temp_c"])),
                "updated_at": float(now),
                "site_id": site_id,
            }
            self._cache[site_id] = entry
            log.info(
                "[WEATHER] %s temp=%.1f°C feels=%.1f°C",
                site_id, entry["temp_c"], entry["feels_like_c"])
            return entry
        except (RuntimeError, OSError, urllib.error.URLError,
                urllib.error.HTTPError, ValueError, TypeError,
                KeyError) as e:
            log.warning("[WEATHER] fetch %s thất bại: %s", site_id, e)
            return None

    def refresh(self, site_id: str, now: float) -> None:
        """Gọi API (blocking) — chỉ từ vòng nền / to_thread."""
        self._try_fetch(site_id, now)

    def refresh_all(self, now: float,
                    site_ids: list[str] | None = None) -> None:
        ids = site_ids or list((self._cfg.get("sites") or {}).keys())
        if not ids:
            ids = [self._cfg.get("default_site_id") or "hanoi-office-4f"]
        for sid in ids:
            self.refresh(sid, now)

    def read_cached(self, site_id: str, now: float) -> dict | None:
        """Chỉ đọc cache — không urlopen (dùng trên request/WS)."""
        site_id = site_id or self._cfg.get("default_site_id")
        cached = self._cache.get(site_id)
        if cached is None:
            return None
        age = now - cached["updated_at"]
        if age > CACHE_MAX_AGE_S:
            return None
        return {
            **cached,
            "source": "cache",
            "label": self._label(site_id),
        }

    def get(self, site_id: str, now: float) -> dict | None:
        """Trả snapshot site hoặc None nếu không có số tin cậy."""
        site_id = site_id or self._cfg.get("default_site_id")
        cached = self._cache.get(site_id)
        age = (now - cached["updated_at"]) if cached else None

        need_fetch = cached is None or (
            age is not None and age >= self.fetch_interval_s)

        if need_fetch:
            fetched = self._try_fetch(site_id, now)
            if fetched is not None:
                return {
                    **fetched,
                    "source": "api",
                    "label": self._label(site_id),
                }
            cached = self._cache.get(site_id)
            age = (now - cached["updated_at"]) if cached else None

        if cached is None:
            return None
        if age is not None and age > CACHE_MAX_AGE_S:
            # Quá 6 giờ — bỏ qua, không dùng số cũ
            log.info(
                "[WEATHER] %s cache tuổi %.0fs > 6h — bỏ qua",
                site_id, age)
            return None
        return {
            **cached,
            "source": "cache",
            "label": self._label(site_id),
        }

    def _label(self, site_id: str) -> str:
        site = (self._cfg.get("sites") or {}).get(site_id) or {}
        return str(site.get("label") or site_id)

    def snapshot(self, now: float,
                 site_ids: list[str] | None = None) -> dict:
        """Map site_id → reading cho /api/state.weather (chỉ cache)."""
        ids = site_ids or list((self._cfg.get("sites") or {}).keys())
        if not ids:
            ids = [self._cfg.get("default_site_id") or "hanoi-office-4f"]
        out = {}
        for sid in ids:
            got = self.read_cached(sid, now)
            if got is not None:
                out[sid] = {
                    "temp_c": got["temp_c"],
                    "feels_like_c": got["feels_like_c"],
                    "updated_at": got["updated_at"],
                    "source": got["source"],
                    "label": got.get("label") or sid,
                }
        return out

    def outdoor_temp_c(self, site_id: str, now: float) -> float | None:
        got = self.read_cached(site_id, now)
        if got is None:
            return None
        return float(got["temp_c"])


def apply_weather_to_esg(
    weather: WeatherService,
    esg_config: dict,
    *,
    site_id: str,
    now: float,
) -> None:
    """Ghi outdoor_temp_c vào cfg ESG từ cache (refresh ở vòng nền)."""
    t = weather.outdoor_temp_c(site_id, now)
    esg_config["outdoor_temp_c"] = t
