"""A/B benchmark ESG — docs/07 §3.2, sáu bước trên cụm giả lập.

Chạy:
    python server.py --ab-benchmark
    python server.py --ab-benchmark --cooldown-s 2

Thời gian là tham số (fake_cluster). Cooldown vẫn kiểm telemetry idle;
`--cooldown-s` mặc định 600 (≥10 phút). Test dùng giá trị nhỏ.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys

from balancer import LoadBalancer
from esg import compute_report
from fake_cluster import heterogeneous_cluster
from forecast_cache import (
    NodeForecast, effective_threshold, apply_hysteresis, MAX_TEMP_MARGIN_C,
)
from scheduler import (
    DEFAULT_WEIGHTS, RoundRobinCursor, schedule_once, reap_expired,
)
from store import TelemetryStore

THRESHOLD_C = 75.0
TICK_DT = 1.0
JOB_DT = 6.0
IDLE_TOLERANCE_C = 2.5


def load_prompts(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if len(data) < 1:
        raise SystemExit("[AB] bộ prompt rỗng")
    return data


def _all_idle(nodes: dict, now: float) -> bool:
    for n in nodes.values():
        if not n.reports_temp or n.idle_temp is None:
            continue
        tel = n.telemetry(now)
        t = tel["cpu_temp"]
        if t is None:
            continue
        if abs(t - n.idle_temp) > IDLE_TOLERANCE_C:
            return False
        if tel["cpu_util"] > 15.0:
            return False
    return True


def _wait_idle(nodes: dict, now: float, cooldown_s: float,
               store: TelemetryStore | None = None) -> float:
    """Bước 4: nghỉ đến khi mọi máy về nhàn rỗi (telemetry)."""
    t = now
    end_min = now + cooldown_s
    while True:
        for n in nodes.values():
            n.tick(TICK_DT, under_load=False)
            if store is not None:
                tel = n.telemetry(t)
                store.insert(n.name, t, tel["cpu_temp"], None,
                             tel["cpu_util"], tel["power_w"])
        t += TICK_DT
        if t >= end_min and _all_idle(nodes, t):
            return t
        if t > end_min + 3600:
            raise RuntimeError(
                "[AB] cooldown: máy không về idle sau 1 giờ mô phỏng")


def _forecast(nodes, cache_prev, now, loads, threshold=THRESHOLD_C):
    cache = {}
    for name, n in nodes.items():
        prev = cache_prev.get(name)
        tel = n.telemetry(now)
        temp = tel["cpu_temp"]
        under = loads.get(name, False)
        if not n.reports_temp:
            cache[name] = NodeForecast(
                node=name, state="READY", predicted_max_c=None,
                current_temp_c=None, cpu_util=tel["cpu_util"],
                power_w=None, power_source="none",
                inflight=prev.inflight if prev else 0,
                max_concurrent=1, model_ready=True,
                last_sample_ts=now, idle_baseline_c=40.0,
                effective_threshold_c=threshold,
                computed_at=now, reason="no temp")
            continue
        baseline = n.idle_temp if n.idle_temp is not None else 40.0
        eff = effective_threshold(threshold, baseline, MAX_TEMP_MARGIN_C)
        pred = temp + (12.0 if under else 3.0)
        state_name, changed_at, reason = apply_hysteresis(
            prev, base_state="READY", pred=pred,
            threshold_c=threshold, now=now)
        span = max(eff - baseline, 1.0)
        headroom = max(0.0, min(1.0, (eff - pred) / span))
        cache[name] = NodeForecast(
            node=name, state=state_name, predicted_max_c=pred,
            current_temp_c=temp, headroom=headroom,
            cpu_util=tel["cpu_util"],
            power_w=tel["power_w"], power_source=tel["power_source"],
            inflight=prev.inflight if prev else 0,
            max_concurrent=1, model_ready=True,
            last_sample_ts=now, idle_baseline_c=baseline,
            effective_threshold_c=eff,
            p_idle_w=n.p_idle_w, p_max_w=n.p_max_w,
            flagged_since=(now if state_name == "AT_RISK" else None),
            state_changed_at=changed_at, computed_at=now, reason=reason,
        )
    return cache


def _run_pass(prompts: list[dict], mode: str, nodes: dict, now: float,
              store: TelemetryStore, threshold: float = THRESHOLD_C) -> float:
    """Một lượt A/B. RR: AT_RISK vẫn nhận job (skip_flagged=True)."""
    q = LoadBalancer(max_queue=500)
    cursor = RoundRobinCursor()
    cache: dict = {}
    loads = {name: False for name in nodes}
    active_until: dict[str, float] = {}
    t = now
    n_jobs = len(prompts)
    for _ in range(n_jobs):
        q.enqueue_job(duration_s=JOB_DT, job_type="chat")

    max_steps = max(300, n_jobs * 25)
    assigned = 0
    for _ in range(max_steps):
        for name in list(active_until):
            if t >= active_until[name]:
                del active_until[name]
                loads[name] = False
                q.complete(name)
                if name in cache:
                    cache[name].inflight = max(0, cache[name].inflight - 1)
        for name in active_until:
            loads[name] = True

        cache = _forecast(nodes, cache, t, loads, threshold)
        reap_expired(cache, q, t)
        schedule_once(cache, q, DEFAULT_WEIGHTS, t, mode=mode,
                      reservation_timeout_s=30.0, rr_cursor=cursor,
                      max_assign=3)

        for name in list(nodes):
            if loads.get(name):
                continue
            job = q.claim(name, now=t)
            if job is None:
                continue
            node = nodes[name]
            tel0 = node.telemetry(t)
            tokens = max(8, int(node.tokens_per_s * JOB_DT * 0.5))
            energy_j = None
            energy_source = "none"
            if tel0["power_w"] is not None:
                p0 = float(tel0["power_w"])
                p1 = p0 + 0.4 * (node.p_max_w - node.p_idle_w)
                energy_j = 0.5 * (p0 + p1) * JOB_DT
                energy_source = "sensor"
            node.tick(JOB_DT * 0.5, under_load=True)

            min_clock = 3200.0
            if (node.temp is not None and node.max_temp is not None
                    and node.temp > node.max_temp - 8):
                min_clock = 1800.0

            detail = {
                "status": "ok",
                "job_id": job["id"],
                "scheduler_mode": mode,
                "energy_j": energy_j,
                "energy_source": energy_source,
                "tokens_out": tokens,
                "tokens_estimated": False,
                "duration_ms": JOB_DT * 1000.0,
                "duration_h": JOB_DT / 3600.0,
                "peak_temp_c": node.temp,
                "min_clock_mhz": min_clock,
                "base_clock_mhz": 3000.0,
                "cpu_util": 85.0,
                "threshold_at_time": threshold,
            }
            store.insert_esg_event(t + JOB_DT, name, "job_completed", detail)
            # schedule_once đã +1 inflight khi reserve — không cộng thêm
            active_until[name] = t + JOB_DT
            loads[name] = True
            assigned += 1

        for n in nodes.values():
            n.tick(TICK_DT, under_load=loads.get(n.name, False))
            tel = n.telemetry(t)
            store.insert(n.name, t, tel["cpu_temp"], None,
                         tel["cpu_util"], tel["power_w"])
        t += TICK_DT

        if (assigned >= n_jobs and not active_until
                and not q.pending() and not q.reserved()):
            break

    print(f"[AB] pass {mode}: assigned={assigned}/{n_jobs} t={t:.0f}s",
          flush=True)
    return t


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    xs = sorted(vals)
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def summarize(events: list[dict], config: dict | None = None) -> dict:
    report = compute_report(events, config)
    t1 = report["tier1_measured"]
    peaks, durs_rr, durs_ta = [], [], []
    for ev in events:
        if ev.get("event_type") != "job_completed":
            continue
        d = ev.get("detail") or {}
        if d.get("peak_temp_c") is not None:
            peaks.append(float(d["peak_temp_c"]))
        dm = d.get("duration_ms")
        if dm is None:
            continue
        mode = d.get("scheduler_mode")
        if mode == "round_robin":
            durs_rr.append(float(dm))
        elif mode == "thermal_aware":
            durs_ta.append(float(dm))
    return {
        "report": report,
        "j_per_token": t1.get("j_per_token"),
        "j_per_token_baseline": t1.get("j_per_token_baseline"),
        "improvement_pct": t1.get("improvement_pct"),
        "throttle_seconds_avoided": t1.get("throttle_seconds_avoided"),
        "latency_median_ms": t1.get("latency_median_ms"),
        "latency_p95_ms": t1.get("latency_p95_ms"),
        "latency_median_rr_ms": (
            float(statistics.median(durs_rr)) if durs_rr else None),
        "latency_p95_rr_ms": _pct(durs_rr, 0.95),
        "cluster_peak_temp_c": max(peaks) if peaks else None,
        "samples": t1.get("samples"),
    }


def run_ab_benchmark(prompts_path: str, cooldown_s: float = 600.0,
                     db_path: str = ":memory:",
                     esg_config: dict | None = None) -> dict:
    import logging
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # Tắt spam log scheduler (Unicode trên cp1252 làm chậm hàng nghìn lần)
    logging.disable(logging.WARNING)

    prompts = load_prompts(prompts_path)
    print(f"[AB] loaded {len(prompts)} prompts from {prompts_path}",
          flush=True)
    print(f"[AB] cooldown_s={cooldown_s} (telemetry idle check bắt buộc)",
          flush=True)

    nodes = heterogeneous_cluster()
    store = TelemetryStore(db_path)
    now = 0.0
    for n in nodes.values():
        tel = n.telemetry(now)
        store.insert(n.name, now, tel["cpu_temp"], None,
                     tel["cpu_util"], tel["power_w"])

    print("[AB] pass A: round_robin (flagged vẫn nhận job)", flush=True)
    now = _run_pass(prompts, "round_robin", nodes, now, store)

    print("[AB] cooldown: chờ máy về nhiệt nhàn rỗi…", flush=True)
    now = _wait_idle(nodes, now, cooldown_s, store)
    print(f"[AB] idle OK at t={now:.0f}s", flush=True)

    print("[AB] pass B: thermal_aware", flush=True)
    now = _run_pass(prompts, "thermal_aware", nodes, now, store)

    events = store.esg_events()
    summary = summarize(events, esg_config)
    _print_table(summary)
    summary["events"] = events
    summary["sim_end_ts"] = now
    logging.disable(logging.NOTSET)
    return summary


def _print_table(s: dict) -> None:
    print()
    print("=" * 64)
    print("  KẾT QUẢ A/B (docs/07 §3.2) — dấu âm được giữ nguyên")
    print("=" * 64)

    def fmt(v, unit=""):
        if v is None:
            return "không khả dụng"
        if isinstance(v, float):
            return f"{v:.4g}{unit}"
        return f"{v}{unit}"

    rows = [
        ("J/token (thermal)", fmt(s.get("j_per_token"), " J")),
        ("J/token (RR mốc)", fmt(s.get("j_per_token_baseline"), " J")),
        ("% cải thiện", fmt(s.get("improvement_pct"), " %")),
        ("Throttle tránh được", fmt(s.get("throttle_seconds_avoided"), " s")),
        ("Độ trễ trung vị (TA)", fmt(s.get("latency_median_ms"), " ms")),
        ("Độ trễ p95 (TA)", fmt(s.get("latency_p95_ms"), " ms")),
        ("Độ trễ trung vị (RR)", fmt(s.get("latency_median_rr_ms"), " ms")),
        ("Nhiệt đỉnh cụm", fmt(s.get("cluster_peak_temp_c"), " °C")),
        ("Mẫu sensor", fmt(s.get("samples"))),
    ]
    for k, v in rows:
        print(f"  {k:<28} {v}")
    imp = s.get("improvement_pct")
    if imp is not None and imp < 0:
        print()
        print("  CẢNH BÁO: cải thiện ÂM — báo cáo đúng dấu (docs/07 §3.2).")
        print("  Lợi ích có thể nằm ở tuổi thọ / ổn định, không ở hóa đơn điện.")
    print("=" * 64)


def default_prompts_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "ab_prompts.json")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ESG A/B benchmark")
    ap.add_argument("--prompts", default=default_prompts_path())
    ap.add_argument("--cooldown-s", type=float, default=600.0)
    ap.add_argument("--db", default=":memory:")
    args = ap.parse_args()
    run_ab_benchmark(args.prompts, cooldown_s=args.cooldown_s,
                     db_path=args.db)
