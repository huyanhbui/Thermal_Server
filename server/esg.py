"""ESG ba tầng — báo cáo thuần từ nhật ký sự kiện (ADR-003, docs/07).

Không cộng gộp ba tầng. Sensor và model không trộn trong một phép cộng.
Báo cáo là hàm thuần: cùng events + config → cùng đầu ra (E10).
"""
from __future__ import annotations

import json
import math
import os
import statistics

# Flat defaults sau khi flatten nested esg_config.json (docs/07 §9).
DEFAULTS = {
    "min_samples_for_confidence": 100,
    "min_samples_to_show": 20,
    "min_sensor_samples_ok": 100,          # alias cũ
    "min_sensor_samples_preliminary": 20,  # alias cũ
    "throttle_clock_ratio": 0.90,
    "base_clock_mhz": 3000.0,  # khi job không gửi base_clock_mhz
    "leakage_w_per_c": None,
    "fan_max_w": 3.0,
    "fan_rpm_max": 5000.0,
    "fan_kwh_factor": 0.0,  # legacy; ưu tiên fan_rpm nếu có
    "cooling_base_factor": 0.25,
    "cooling_weather_k": 0.02,
    "cooling_reference_temp_c": 25.0,
    "outdoor_temp_c": None,
    "scale_nodes": 1000,
    "scale_days": 365,
    "price_usd_per_kwh": 0.10,
    "price_vnd_per_kwh": 2500,
    "co2_kg_per_kwh": 0.72,
    "co2_source_year": 2024,
    "carbon_price_usd_per_tco2": 20.0,
    "threshold_margin_above_idle_c": 8.0,
    "node_power_kw": 0.065,
    "cooling_overhead_factor": 0.25,
}

TIER3_LABEL = "DỰ PHÓNG — không phải số đo"

_NESTED_SECTIONS = ("tier1", "tier2", "tier3", "anti_gaming", "legacy")


def _flatten_esg_dict(raw: dict) -> dict:
    """Nested §9 → flat keys dùng trong compute_report."""
    out: dict = {}
    for key, val in raw.items():
        if key.startswith("_") or key == "_comment":
            continue
        if key in _NESTED_SECTIONS and isinstance(val, dict):
            for k2, v2 in val.items():
                if k2.startswith("_"):
                    continue
                out[k2] = v2
        elif not isinstance(val, dict):
            out[key] = val
    # Đồng bộ alias độ tin cậy
    if "min_samples_to_show" in out:
        out["min_sensor_samples_preliminary"] = out["min_samples_to_show"]
    if "min_samples_for_confidence" in out:
        out["min_sensor_samples_ok"] = out["min_samples_for_confidence"]
    return out


def load_esg_config(path):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        cfg.update(_flatten_esg_dict(raw))
    return cfg


def config_sources_ok(path) -> list[str]:
    """Trả danh sách khóa số thiếu _source (rỗng = đạt kiểm chứng #11)."""
    if not os.path.exists(path):
        return ["file_missing"]
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    missing = []
    for section in _NESTED_SECTIONS:
        block = raw.get(section)
        if not isinstance(block, dict):
            continue
        for k, v in block.items():
            if k.startswith("_") or k == "_comment":
                continue
            if not isinstance(v, (int, float)) and v is not None:
                continue
            # null vẫn cần _source giải thích
            src = (block.get(f"_{k}_source")
                   or block.get(f"_{k.split('_')[0]}_source"))
            # chấp nhận pattern _leakage_source cho leakage_w_per_c
            stem = k.split("_")[0]
            if src is None:
                for sk in block:
                    if sk.startswith("_") and stem in sk and sk.endswith(
                            "_source"):
                        src = block[sk]
                        break
            if src is None and f"_{k}_source" not in block:
                # heuristic: _fan_source covers fan_max_w
                covered = False
                for sk, sv in block.items():
                    if (sk.startswith("_") and sk.endswith("_source")
                            and isinstance(sv, str)):
                        # fan_max_w ← _fan_source; cooling_* ← _cooling_source
                        stem_src = sk[1:].replace("_source", "")
                        if k.startswith(stem_src) or stem_src in k:
                            covered = True
                            break
                if not covered:
                    missing.append(f"{section}.{k}")
    return missing


def _detail(ev) -> dict:
    d = ev.get("detail") or ev.get("detail_json")
    if d is None:
        return {}
    if isinstance(d, dict):
        return d
    if isinstance(d, str):
        try:
            return json.loads(d) or {}
        except json.JSONDecodeError:
            return {}
    return {}


def _confidence(samples: int, cfg: dict) -> str:
    show = int(cfg.get("min_samples_to_show",
                       cfg.get("min_sensor_samples_preliminary", 20)))
    ok = int(cfg.get("min_samples_for_confidence",
                     cfg.get("min_sensor_samples_ok", 100)))
    if samples < show:
        return "chưa đủ dữ liệu"
    if samples < ok:
        return "sơ bộ"
    return "ok"


def _j_per_token(jobs: list[dict]) -> tuple[float | None, int, float, float]:
    """Trả (j_per_token, samples, sum_energy_j, sum_tokens). Chỉ job có J+token."""
    e_sum = 0.0
    t_sum = 0.0
    n = 0
    for j in jobs:
        if j.get("tokens_estimated"):
            continue
        ej = j.get("energy_j")
        to = j.get("tokens_out")
        if ej is None or to is None or to <= 0:
            continue
        e_sum += float(ej)
        t_sum += float(to)
        n += 1
    if t_sum <= 0 or n == 0:
        return None, n, e_sum, t_sum
    return e_sum / t_sum, n, e_sum, t_sum


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def _tier2_leakage_kwh(jobs: list[dict], leakage_w: float) -> tuple[float, bool]:
    """Σ (ΔT_avoided × W/°C × h) / 1000."""
    total = 0.0
    used = False
    for j in jobs:
        d_t = j.get("delta_t_avoided_c")
        dur_h = j.get("duration_h")
        if d_t is None or dur_h is None:
            continue
        try:
            total += float(d_t) * leakage_w * float(dur_h) / 1000.0
            used = True
        except (TypeError, ValueError):
            continue
    return total, used


def _fan_kwh_saved(jobs: list[dict], fan_max_w: float,
                   rpm_max: float) -> tuple[float, bool]:
    """Ước lượng ΔP quạt ~ P_max × (rpm/rpm_max)³ giữa máy nóng–mát.

    Khi job có fan_rpm_hot và fan_rpm_cool: dùng cặp đó.
    Khi chỉ có fan_rpm: không tính được Δ → bỏ qua.
    """
    total = 0.0
    used = False
    if fan_max_w <= 0 or rpm_max <= 0:
        return 0.0, False
    for j in jobs:
        hot = j.get("fan_rpm_hot")
        cool = j.get("fan_rpm_cool")
        dur_h = j.get("duration_h")
        if hot is None or cool is None or dur_h is None:
            continue
        try:
            rh = min(max(float(hot) / rpm_max, 0.0), 1.0)
            rc = min(max(float(cool) / rpm_max, 0.0), 1.0)
            p_hot = fan_max_w * (rh ** 3)
            p_cool = fan_max_w * (rc ** 3)
            delta = max(0.0, p_hot - p_cool)
            total += delta * float(dur_h) / 1000.0
            used = True
        except (TypeError, ValueError):
            continue
    return total, used


def cooling_factor(cfg: dict) -> float:
    """base × (1 + k × max(0, T_ngoài − T_tham chiếu))."""
    base = float(cfg.get("cooling_base_factor", 0.25) or 0.25)
    k = float(cfg.get("cooling_weather_k", 0.02) or 0.0)
    t_ref = float(cfg.get("cooling_reference_temp_c", 25.0) or 25.0)
    t_out = cfg.get("outdoor_temp_c")
    if t_out is None:
        return base
    try:
        return base * (1.0 + k * max(0.0, float(t_out) - t_ref))
    except (TypeError, ValueError):
        return base


def _is_throttled(job: dict, cfg: dict) -> bool:
    """throttle = (clock < base×ratio) ∧ (util > 70). Thiếu clock → False."""
    mc = job.get("min_clock_mhz")
    if mc is None:
        return False
    util = job.get("cpu_util")
    if util is None:
        # Không có util: không khẳng định throttle (docs: cần cả hai điều kiện)
        return False
    try:
        if float(util) <= 70.0:
            return False
        base = job.get("base_clock_mhz")
        if base is None:
            base = cfg.get("base_clock_mhz", 3000.0)
        ratio = float(cfg.get("throttle_clock_ratio", 0.90))
        return float(mc) < float(base) * ratio
    except (TypeError, ValueError):
        return False


def _filter_events(events: list[dict], from_ts: float | None,
                   to_ts: float | None) -> list[dict]:
    out = []
    for ev in events:
        ts = ev.get("ts")
        if ts is None:
            continue
        ts = float(ts)
        if from_ts is not None and ts < from_ts:
            continue
        if to_ts is not None and ts > to_ts:
            continue
        out.append(ev)
    return out


def _split_threshold_segments(
        events: list[dict]) -> list[tuple[float, float | None, float | None]]:
    """Cắt theo threshold_changed. Trả [(threshold_c, from_ts, to_ts), ...].

    threshold_c lấy từ detail.new của threshold_changed, hoặc
    threshold_at_time trên sự kiện đầu tiên của khoảng.
    """
    if not events:
        return []
    changes = []
    for ev in events:
        if ev.get("event_type") != "threshold_changed":
            continue
        d = _detail(ev)
        new_th = d.get("new")
        if new_th is None:
            continue
        changes.append((float(ev["ts"]), float(new_th)))
    changes.sort(key=lambda x: x[0])

    # Ngưỡng ban đầu: threshold_at_time của sự kiện sớm nhất, hoặc 75
    first_th = 75.0
    for ev in events:
        d = _detail(ev)
        tat = d.get("threshold_at_time")
        if tat is not None:
            first_th = float(tat)
            break

    ts0 = float(events[0]["ts"])
    ts_end = float(events[-1]["ts"])

    if not changes:
        return [(first_th, ts0, ts_end)]

    segments = []
    # Khoảng trước change đầu (nếu có sự kiện trước)
    if changes[0][0] > ts0:
        # ngưỡng trước lần đổi đầu = old của change, hoặc first_th
        d0 = None
        for ev in events:
            if (ev.get("event_type") == "threshold_changed"
                    and float(ev["ts"]) == changes[0][0]):
                d0 = _detail(ev)
                break
        pre_th = float(d0["old"]) if d0 and d0.get("old") is not None else first_th
        segments.append((pre_th, ts0, changes[0][0]))

    for i, (cts, nth) in enumerate(changes):
        to = changes[i + 1][0] if i + 1 < len(changes) else ts_end
        segments.append((nth, cts, to))
    return segments


def _compute_tiers(events: list[dict], cfg: dict) -> dict:
    """Tính ba tầng cho một tập sự kiện (một khoảng ngưỡng)."""
    completed = []
    for ev in events:
        if ev.get("event_type") != "job_completed":
            continue
        d = _detail(ev)
        if (d.get("status") or "ok") != "ok":
            continue
        # gắn ts/node để latency/scale
        row = dict(d)
        row["_ts"] = ev.get("ts")
        row["_node"] = ev.get("node")
        completed.append(row)

    sensor_jobs = [j for j in completed
                   if j.get("energy_source") == "sensor"]
    model_jobs = [j for j in completed
                  if j.get("energy_source") == "model"]

    by_mode: dict[str, list] = {}
    for j in sensor_jobs:
        mode = j.get("scheduler_mode") or "thermal_aware"
        by_mode.setdefault(mode, []).append(j)

    jpt, samples, e_sensor, _tok = _j_per_token(sensor_jobs)
    jpt_rr, _, _, _ = _j_per_token(by_mode.get("round_robin", []))
    jpt_ta, _, _, _ = _j_per_token(by_mode.get("thermal_aware", []))

    show_n = int(cfg.get("min_samples_to_show", 20))
    improvement = None
    # E5: không hiện % khi thiếu mẫu; E8: cho phép âm
    if (samples >= show_n and jpt_rr is not None and jpt_ta is not None
            and jpt_rr > 0):
        improvement = (jpt_rr - jpt_ta) / jpt_rr * 100.0

    # Throttle — CHỈ job sensor (bất biến 4: không trộn model vào Tầng 1)
    any_clock = any(
        j.get("min_clock_mhz") is not None for j in sensor_jobs)
    throttle_rr = 0.0
    throttle_ta = 0.0
    if any_clock:
        for j in sensor_jobs:
            if not _is_throttled(j, cfg):
                continue
            dur = j.get("duration_ms") or 0.0
            sec = float(dur) / 1000.0
            mode = j.get("scheduler_mode") or "thermal_aware"
            if mode == "round_robin":
                throttle_rr += sec
            else:
                throttle_ta += sec
        # Có thể âm nếu thermal throttle nhiều hơn — báo cáo đúng dấu
        throttle_avoided: float | None = throttle_rr - throttle_ta
    else:
        throttle_avoided = None

    def _latencies(jobs: list[dict]) -> tuple[float | None, float | None]:
        vals = []
        for j in jobs:
            dm = j.get("duration_ms")
            if dm is not None:
                try:
                    vals.append(float(dm))
                except (TypeError, ValueError):
                    pass
        if not vals:
            return None, None
        try:
            med = float(statistics.median(vals))
        except statistics.StatisticsError:
            med = None
        return med, _percentile(vals, 0.95)

    lat_med, lat_p95 = _latencies(sensor_jobs)
    lat_med_rr, _ = _latencies(by_mode.get("round_robin", []))

    tier1 = {
        "j_per_token": jpt,
        "j_per_token_baseline": jpt_rr,
        "improvement_pct": improvement,
        "throttle_seconds_avoided": throttle_avoided,
        "latency_median_ms": lat_med,
        "latency_p95_ms": lat_p95,
        "latency_median_baseline_ms": lat_med_rr,
        "samples": samples,
        "confidence": _confidence(samples, cfg),
        "sensor_nodes": sorted({j.get("_node") for j in sensor_jobs
                                if j.get("_node")}),
    }

    # —— Tầng 2 ——
    assumptions: list[str] = []
    leakage_raw = cfg.get("leakage_w_per_c")
    tier2_jobs = [j for j in completed
                  if j.get("energy_source") in ("sensor", "model")]
    if leakage_raw is None:
        kwh_leakage = 0.0
        used_rows = False
        assumptions.append(
            "hệ số rò chưa đo (leakage_w_per_c=null) — Tầng 2 rò = 0")
    else:
        leakage_w = float(leakage_raw)
        kwh_leakage, used_rows = _tier2_leakage_kwh(tier2_jobs, leakage_w)
        assumptions.append(f"hệ số rò {leakage_w} W/°C (cấu hình)")
        if not used_rows:
            assumptions.append("thiếu ΔT/thời lượng — Tầng 2 rò = 0")

    fan_max = float(cfg.get("fan_max_w", 3.0) or 0.0)
    rpm_max = float(cfg.get("fan_rpm_max", 5000.0) or 5000.0)
    kwh_fan, fan_used = _fan_kwh_saved(tier2_jobs, fan_max, rpm_max)
    if not fan_used:
        # legacy fallback: fan_kwh_factor × leakage
        ff = float(cfg.get("fan_kwh_factor", 0.0) or 0.0)
        if ff and kwh_leakage:
            kwh_fan = kwh_leakage * ff
            assumptions.append(
                f"điện quạt: fan_kwh_factor={ff} × rò (không có fan_rpm)")
        else:
            kwh_fan = 0.0
            assumptions.append("điện quạt: không khả dụng (thiếu fan_rpm)")
    else:
        assumptions.append(
            f"quạt ~ bậc 3 theo tốc độ, P_max {fan_max} W")

    cf = cooling_factor(cfg)
    kwh_cooling = (kwh_leakage + kwh_fan) * cf
    if cfg.get("outdoor_temp_c") is None:
        assumptions.append(
            f"làm mát phòng hệ số {cf:.2f} (base, chưa có T ngoài trời)")
    else:
        assumptions.append(
            f"làm mát phòng hệ số {cf:.2f} "
            f"(base + hiệu chỉnh T ngoài {cfg['outdoor_temp_c']}°C)")

    if model_jobs:
        assumptions.append(
            "job energy_source=model chỉ góp Tầng 2 (không vào Tầng 1)")

    tier2 = {
        "kwh_leakage_saved": kwh_leakage,
        "kwh_fan_saved": kwh_fan,
        "kwh_cooling_saved": kwh_cooling,
        "cooling_factor": cf,
        "assumptions": assumptions,
    }

    # —— Tầng 3: chiếu riêng, không cộng ——
    kwh_measured = e_sensor / 3_600_000.0
    kwh_derived = kwh_leakage + kwh_fan + kwh_cooling
    scale_n = float(cfg.get("scale_nodes", 1000))
    scale_d = float(cfg.get("scale_days", 365))
    ts_list = [float(j["_ts"]) for j in completed if j.get("_ts") is not None]
    nodes = {j.get("_node") for j in completed if j.get("_node")}
    if len(ts_list) >= 2:
        hours = max((max(ts_list) - min(ts_list)) / 3600.0, 1.0 / 3600.0)
    else:
        hours = 1.0 / 3600.0
    n_real = max(len(nodes), 1)
    denom = n_real * hours
    hours_proj = scale_d * 24.0

    def _project(kwh: float) -> float:
        return (kwh / denom) * scale_n * hours_proj

    kwh_pm = _project(kwh_measured)
    kwh_pd = _project(kwh_derived)
    price_vnd = float(cfg["price_vnd_per_kwh"])
    co2 = float(cfg["co2_kg_per_kwh"])
    carbon_usd = float(cfg.get("carbon_price_usd_per_tco2", 20.0) or 0.0)
    # Tín chỉ tiềm năng chỉ trên derived đã chiếu (Tầng 3)
    credit_vnd = (kwh_pd * co2 / 1000.0) * carbon_usd * price_vnd / max(
        float(cfg.get("price_usd_per_kwh", 0.10) or 0.10), 1e-9)
    # Đơn giản hơn: credit = tCO2 × USD/t × VND/USD gần đúng qua price ratio
    # Dùng: tCO2 × carbon_price_usd × (vnd_per_kwh / usd_per_kwh) không đúng.
    # Spec: hiện ước lượng ₫. Dùng co2_kg × (carbon_usd/1000) × VND_per_USD≈25000.
    vnd_per_usd = 25000.0
    credit_vnd = (kwh_pd * co2 / 1000.0) * carbon_usd * vnd_per_usd

    scale_note = (
        f"Ở quy mô {int(scale_n)} máy trong {int(scale_d)} ngày. "
        f"Quy mô thử nghiệm hiện tại là {n_real} máy trong {hours:.2f} giờ."
    )
    tier3 = {
        "scale_nodes": scale_n,
        "scale_days": scale_d,
        "experiment_nodes": n_real,
        "experiment_hours": hours,
        "scale_note": scale_note,
        "kwh_projected_measured": kwh_pm,
        "kwh_projected_derived": kwh_pd,
        "vnd_projected_measured": kwh_pm * price_vnd,
        "vnd_projected_derived": kwh_pd * price_vnd,
        "co2_kg_projected_measured": kwh_pm * co2,
        "co2_kg_projected_derived": kwh_pd * co2,
        "carbon_credit_vnd_potential": credit_vnd,
        "label_measured": (
            "CHIẾU TỪ SỐ ĐO (Tầng 1) — không phải tiết kiệm đã chứng minh"),
        "label_derived": TIER3_LABEL + " (chỉ từ Tầng 2)",
        "label": TIER3_LABEL,
    }

    return {
        "tier1_measured": tier1,
        "tier2_derived": tier2,
        "tier3_projected": tier3,
    }


def compute_report(events: list[dict], config: dict | None = None,
                   now: float | None = None,
                   from_ts: float | None = None,
                   to_ts: float | None = None) -> dict:
    """Hàm thuần: cùng events + config → cùng báo cáo (E10).

    Khi ngưỡng đổi giữa kỳ → thêm segments[] (E9); top-level = khoảng mới nhất.
    """
    cfg = dict(DEFAULTS)
    if config:
        cfg.update(config)

    filtered = _filter_events(events, from_ts, to_ts)
    # Sắp theo ts để tách khoảng ổn định
    filtered = sorted(filtered, key=lambda e: float(e.get("ts") or 0))

    segs_meta = _split_threshold_segments(filtered)
    if not segs_meta:
        empty = _compute_tiers([], cfg)
        return empty

    segment_reports = []
    for th, a, b in segs_meta:
        # Khoảng [a, b]: sự kiện ở biên change thuộc khoảng mới
        chunk = []
        for ev in filtered:
            ts = float(ev["ts"])
            if a is not None and ts < a:
                continue
            if b is not None and ts > b:
                continue
            # threshold_changed tại đúng a thuộc khoảng mới — không tính job
            chunk.append(ev)
        tiers = _compute_tiers(chunk, cfg)
        segment_reports.append({
            "threshold_c": th,
            "from_ts": a,
            "to_ts": b,
            **tiers,
        })

    latest = segment_reports[-1]
    out = {
        "tier1_measured": latest["tier1_measured"],
        "tier2_derived": latest["tier2_derived"],
        "tier3_projected": latest["tier3_projected"],
    }
    if len(segment_reports) >= 2:
        out["segments"] = segment_reports
    return out


def kwh_saved(hot_hours, node_power_kw, cooling_overhead_factor):
    """Legacy PoC — không dùng cho báo cáo ba tầng."""
    return hot_hours * node_power_kw * cooling_overhead_factor


def money_saved(kwh, price_per_kwh):
    return kwh * price_per_kwh


def co2_avoided_kg(kwh, grid_emission_factor):
    return kwh * grid_emission_factor


class EsgTracker:
    """Chỉ theo dõi khoảng gắn cờ trong RAM — báo cáo dùng compute_report."""

    def __init__(self, config):
        self.config = config
        self._flagged_since = {}
        self._accumulated_s = 0.0

    def node_flagged(self, node, now):
        self._flagged_since.setdefault(node, now)

    def node_cleared(self, node, now):
        start = self._flagged_since.pop(node, None)
        if start is not None:
            self._accumulated_s += now - start

    def report(self, now=None, events: list | None = None):
        if events is not None:
            return compute_report(events, self.config, now)
        return compute_report([], self.config, now)
