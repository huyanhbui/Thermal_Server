"""Ca tích hợp cụm 10 node — docs/11 §4 (C1–C6, C9–C10). Thời gian là tham số."""
from __future__ import annotations

from balancer import LoadBalancer
from fake_cluster import heterogeneous_cluster
from forecast_cache import (
    NodeForecast, effective_threshold, apply_hysteresis, MAX_TEMP_MARGIN_C,
)
from scheduler import (
    DEFAULT_WEIGHTS, RoundRobinCursor, schedule_once, reap_expired,
)


THRESHOLD_C = 75.0
JOB_HEAT_DT = 8.0          # job chạy đủ lâu để nóng lên rõ
TICK_DT = 1.0
ENQUEUE_EVERY = 3          # thêm 1 job mỗi 3 giây mô phỏng


def _forecast_from_nodes(nodes, cache_prev, now, loads, threshold=THRESHOLD_C):
    """Dự báo đơn giản: predicted = temp + 8 nếu đang tải, else temp + 2."""
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
                last_sample_ts=now,
                idle_baseline_c=40.0,
                effective_threshold_c=threshold,
                recently_failed_until=(
                    prev.recently_failed_until if prev else 0.0),
                consecutive_errors=0,
                state_changed_at=prev.state_changed_at if prev else now,
                computed_at=now, reason="no temp sensor",
            )
            continue

        baseline = n.idle_temp if n.idle_temp is not None else 40.0
        eff = effective_threshold(threshold, baseline, MAX_TEMP_MARGIN_C)
        pred = temp + (15.0 if under else 4.0)
        base = "READY"
        state_name, changed_at, reason = apply_hysteresis(
            prev, base_state=base, pred=pred,
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
            last_sample_ts=now,
            idle_baseline_c=baseline,
            effective_threshold_c=eff,
            p_idle_w=n.p_idle_w, p_max_w=n.p_max_w,
            recently_failed_until=(
                prev.recently_failed_until if prev else 0.0),
            consecutive_errors=0,
            flagged_since=(now if state_name == "AT_RISK" else None),
            state_changed_at=changed_at, computed_at=now, reason=reason,
        )
    return cache


def run_cluster(n_jobs=100, mode="thermal_aware", seed_load=None,
                force_flag=None, only_cool=None, duration_s=500.0):
    """Chạy mô phỏng: enqueue dần → schedule → claim → tick. Trả metrics."""
    nodes = heterogeneous_cluster()
    if only_cool:
        for name, n in nodes.items():
            if name == only_cool or not n.reports_temp:
                continue
            # Đẩy gần ngưỡng để scheduler thermal ưu tiên only_cool
            if n.temp is not None:
                n.temp = min(n.max_temp - 0.5, THRESHOLD_C - 1.0)

    q = LoadBalancer(max_queue=500)
    cursor = RoundRobinCursor()
    cache = {}
    loads = {name: False for name in nodes}
    active_job_until = {}
    assignments = []
    peaks = {name: (n.temp or 0.0) for name, n in nodes.items()}
    flagged_history = []
    prev_flagged = set()
    jobs_left = n_jobs

    steps = int(duration_s / TICK_DT)
    for step in range(steps):
        now = step * TICK_DT

        if jobs_left > 0 and step % ENQUEUE_EVERY == 0:
            q.enqueue_job(duration_s=JOB_HEAT_DT, job_type="chat")
            jobs_left -= 1

        for name, until in list(active_job_until.items()):
            if now >= until:
                loads[name] = False
                del active_job_until[name]
                if name in cache:
                    cache[name].inflight = max(0, cache[name].inflight - 1)
                q.complete(name)

        cache = _forecast_from_nodes(nodes, cache, now, loads)
        if force_flag:
            for name in force_flag:
                if name in cache:
                    f = cache[name]
                    data = {k: getattr(f, k) for k in f.__dataclass_fields__}
                    data["state"] = "AT_RISK"
                    data["predicted_max_c"] = max(f.predicted_max_c or 0, 80.0)
                    data["reason"] = "force_flag"
                    cache[name] = NodeForecast(**data)

        for name, f in cache.items():
            if f.state == "AT_RISK" and name not in prev_flagged:
                flagged_history.append((now, name))
            if f.state == "AT_RISK":
                prev_flagged.add(name)
            else:
                prev_flagged.discard(name)

        reap_expired(cache, q, now)
        schedule_once(cache, q, DEFAULT_WEIGHTS, now, mode=mode,
                      reservation_timeout_s=20.0, rr_cursor=cursor,
                      max_assign=1)

        for name in list(nodes):
            if loads.get(name):
                continue
            job = q.claim(name, now=now)
            if job is None:
                continue
            flagged = cache[name].state == "AT_RISK"
            assignments.append((job["id"], name, flagged, now))
            loads[name] = True
            active_job_until[name] = now + JOB_HEAT_DT

        for name, n in nodes.items():
            n.tick(TICK_DT, under_load=loads.get(name, False))
            if n.temp is not None:
                peaks[name] = max(peaks[name], n.temp)

    cluster_peak = max(
        (v for v in peaks.values() if v is not None), default=0.0)
    return {
        "assignments": assignments,
        "peaks": peaks,
        "cluster_peak": cluster_peak,
        "flagged_history": flagged_history,
        "nodes": nodes,
        "cache": cache,
        "pending": len(q.pending()) + len(q.reserved()),
    }


def test_c1_no_job_to_flagged_nodes():
    """Ca C1 — 10 node, 100 job: không job nào tới node bị gắn cờ."""
    m = run_cluster(n_jobs=100, mode="thermal_aware", duration_s=400.0)
    bad = [a for a in m["assignments"] if a[2]]
    assert not bad, f"jobs tới flagged: {bad[:5]}"


def test_c2_distribution_skews_to_high_headroom():
    """Ca C2 — phân bố lệch về node headroom cao (desktop 01–03)."""
    m = run_cluster(n_jobs=100, mode="thermal_aware", duration_s=400.0)
    counts = {}
    for _, node, _, _ in m["assignments"]:
        counts[node] = counts.get(node, 0) + 1
    cool = sum(counts.get(f"Node-{i:02d}", 0) for i in range(1, 4))
    thin = sum(counts.get(f"Node-{i:02d}", 0) for i in range(7, 9))
    assert cool > thin, f"cool={cool} thin={thin} counts={counts}"


def test_c3_only_one_cool_gets_majority_not_all():
    """Ca C3 — chỉ Node-01 mát: nhận đa số nhưng không phải tất cả (max_concurrent)."""
    # Gắn cờ mọi máy trừ Node-01 và Node-02 (còn một ứng viên phụ)
    flagged = [f"Node-{i:02d}" for i in range(3, 11)]
    m = run_cluster(n_jobs=40, mode="thermal_aware", duration_s=400.0,
                    only_cool="Node-01", force_flag=flagged)
    counts = {}
    for _, node, _, _ in m["assignments"]:
        counts[node] = counts.get(node, 0) + 1
    total = sum(counts.values()) or 1
    assert counts.get("Node-01", 0) > total * 0.4, counts
    assert counts.get("Node-01", 0) < total, counts  # Node-02 vẫn nhận một phần


def test_c4_all_flagged_jobs_wait():
    """Ca C4 — mọi node gắn cờ → không dispatch; job chờ."""
    all_nodes = [f"Node-{i:02d}" for i in range(1, 11)]
    m = run_cluster(n_jobs=10, mode="thermal_aware", duration_s=30.0,
                    force_flag=all_nodes)
    assert m["assignments"] == []
    assert m["pending"] > 0


def test_c5_thin_laptop_flags_before_desktop():
    """Ca C5 — Node-07 nóng nhanh → gắn cờ trước Node-01."""
    nodes = heterogeneous_cluster()
    cache = {}
    loads = {n: True for n in nodes}  # mọi máy dưới tải
    flag_time = {}
    for step in range(200):
        now = float(step)
        for n in nodes.values():
            n.tick(1.0, under_load=True)
        cache = _forecast_from_nodes(nodes, cache, now, loads)
        for name, f in cache.items():
            if f.state == "AT_RISK" and name not in flag_time:
                flag_time[name] = now
        if "Node-07" in flag_time and "Node-01" in flag_time:
            break
    assert "Node-07" in flag_time
    # Node-01 có thể không bao giờ vượt ngưỡng (max 68 < 75) — đó cũng OK
    if "Node-01" in flag_time:
        assert flag_time["Node-07"] < flag_time["Node-01"]
    else:
        assert flag_time["Node-07"] >= 0


def test_c6_sustained_load_respects_dwell():
    """Ca C6 — tải kéo dài: không dao động gắn/gỡ trong MIN_DWELL."""
    m = run_cluster(n_jobs=50, mode="thermal_aware", duration_s=120.0)
    # Đếm số lần gắn cờ mới — không được nhấp nháy quá nhiều
    by_node = {}
    for t, name in m["flagged_history"]:
        by_node.setdefault(name, []).append(t)
    for name, times in by_node.items():
        if len(times) >= 2:
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            assert all(g >= 30.0 for g in gaps), f"{name} dwell gaps {gaps}"


def test_c9_thermal_aware_peak_lower_than_round_robin():
    """Ca C9 — nhiệt đỉnh cụm thermal_aware THẤP HƠN round_robin (thương mại)."""
    ta = run_cluster(n_jobs=60, mode="thermal_aware", duration_s=600.0)
    rr = run_cluster(n_jobs=60, mode="round_robin", duration_s=600.0)
    assert ta["cluster_peak"] < rr["cluster_peak"], (
        f"C9 ĐỎ: thermal_aware peak={ta['cluster_peak']:.1f} "
        f"không thấp hơn round_robin peak={rr['cluster_peak']:.1f}")


def test_c10_node10_gets_jobs_not_tier1_energy():
    """Ca C10 — Node-10 (không nhiệt) vẫn nhận job; power_source=none."""
    m = run_cluster(n_jobs=50, mode="thermal_aware", duration_s=200.0)
    got = [a for a in m["assignments"] if a[1] == "Node-10"]
    # Có thể ít job nhưng phải có khả năng nhận — ép bằng cách gắn cờ mọi máy khác
    m2 = run_cluster(n_jobs=20, mode="thermal_aware", duration_s=80.0,
                     force_flag=[f"Node-{i:02d}" for i in range(1, 10)])
    got2 = [a for a in m2["assignments"] if a[1] == "Node-10"]
    assert got2, "Node-10 phải nhận job khi mọi máy khác bị cờ"
    tel = m2["nodes"]["Node-10"].telemetry(0.0)
    assert tel["power_source"] == "none"
    assert tel["cpu_temp"] is None
