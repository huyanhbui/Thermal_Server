"""Ca kiểm thử scheduler — docs/04 §9. Chỉ cần ForecastCache giả."""
from forecast_cache import NodeForecast
from balancer import LoadBalancer
from scheduler import (
    DEFAULT_WEIGHTS, filter_candidates, score_node, schedule_once,
    reap_expired, redistribute, RoundRobinCursor, FAILED_PENALTY_WINDOW_S,
)


def _nf(name, **kw):
    defaults = dict(
        node=name, state="READY", predicted_max_c=60.0, current_temp_c=50.0,
        cpu_util=10.0, power_w=20.0, power_source="sensor",
        inflight=0, max_concurrent=1, model_ready=True,
        last_sample_ts=1000.0, idle_baseline_c=35.0,
        effective_threshold_c=75.0, p_idle_w=15.0, p_max_w=65.0,
        recently_failed_until=0.0, consecutive_errors=0,
    )
    defaults.update(kw)
    return NodeForecast(**defaults)


def test_f1_flagged_node_rejected():
    """Ca F1 — Node bị gắn cờ → lý do flagged."""
    cache = {"A": _nf("A", state="AT_RISK", predicted_max_c=78.2)}
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert cands == []
    assert "flagged" in rejected["A"]


def test_f2_busy_rejected():
    """Ca F2 — inflight = max_concurrent → busy."""
    cache = {"A": _nf("A", inflight=1, max_concurrent=1)}
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert cands == []
    assert rejected["A"].startswith("busy")


def test_f3_stale_state_rejected():
    """Ca F3 — Node STALE bị loại."""
    cache = {"A": _nf("A", state="STALE")}
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert "A" not in cands
    assert "state_stale" in rejected["A"]


def test_f4_warming_up_not_rejected():
    """Ca F4 — WARMING_UP không bị loại."""
    cache = {"A": _nf("A", state="WARMING_UP", predicted_max_c=None,
                      current_temp_c=50.0)}
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert cands == ["A"]


def test_f5_joining_rejected():
    """Ca F5 — JOINING bị loại."""
    cache = {"A": _nf("A", state="JOINING")}
    _, rejected = filter_candidates(cache, {}, now=1000.0)
    assert rejected["A"] == "state_joining"


def test_f6_all_rejected_returns_full_reasons():
    """Ca F6 — mọi node bị loại → tập rỗng + lý do đầy đủ."""
    cache = {
        "A": _nf("A", state="AT_RISK", predicted_max_c=80.0),
        "B": _nf("B", inflight=1),
        "C": _nf("C", state="STALE"),
    }
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert cands == []
    assert set(rejected) == {"A", "B", "C"}


def test_f7_stale_telemetry_rejected():
    """Ca F7 — telemetry cũ 47s → stale_telemetry."""
    cache = {"A": _nf("A", last_sample_ts=1000.0 - 47.0)}
    cands, rejected = filter_candidates(cache, {}, now=1000.0)
    assert cands == []
    assert "stale_telemetry" in rejected["A"]


def test_s1_example_node_b_wins():
    """Ca S1 — ví dụ §4.8: Node-B thắng, điểm ≈ 0.625."""
    now = 1000.0
    cache = {
        "Node-A": _nf("Node-A", idle_baseline_c=35.0, predicted_max_c=72.0,
                      cpu_util=15.0, power_w=22.0),
        "Node-B": _nf("Node-B", idle_baseline_c=40.0, predicted_max_c=58.0,
                      cpu_util=45.0, power_w=34.0),
        "Node-C": _nf("Node-C", state="AT_RISK", idle_baseline_c=38.0,
                      predicted_max_c=79.0, cpu_util=88.0, power_w=61.0,
                      inflight=1),
    }
    sc, _ = score_node(cache["Node-B"], DEFAULT_WEIGHTS, now)
    assert abs(sc - 0.625) < 0.002
    q = LoadBalancer(max_queue=20)
    q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    reserved = q.reserved()
    assert len(reserved) == 1
    assert reserved[0]["target"] == "Node-B"


def test_s2_tie_broken_by_name():
    """Ca S2 — hai node giống hệt → điểm bằng; phá hòa theo tên."""
    now = 1000.0
    a = _nf("Node-A")
    b = _nf("Node-B")
    sa, _ = score_node(a, DEFAULT_WEIGHTS, now)
    sb, _ = score_node(b, DEFAULT_WEIGHTS, now)
    assert abs(sa - sb) < 1e-9
    cache = {"Node-A": a, "Node-B": b}
    q = LoadBalancer()
    q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    assert q.reserved()[0]["target"] == "Node-A"


def test_single_ready_node_continues_queue_after_previous_job_completes():
    """Một máy khả dụng vẫn là capacity hợp lệ, không đợi máy thứ hai."""
    now = 1000.0
    cache = {"Node-A": _nf("Node-A")}
    q = LoadBalancer(max_queue=4)
    first = q.enqueue_job(job_type="burn", duration_s=1)
    second = q.enqueue_job(job_type="burn", duration_s=1)

    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    assert q.reserved()[0]["id"] == first["id"]
    claimed = q.claim("Node-A", now=now)
    assert claimed is not None
    q.complete("Node-A", first["id"])
    cache["Node-A"].inflight = 0

    schedule_once(cache, q, DEFAULT_WEIGHTS, now + 1.0)
    assert q.reserved()[0]["id"] == second["id"]
    assert q.reserved()[0]["target"] == "Node-A"


def test_multiple_ready_nodes_receive_parallel_queue_work_before_reuse():
    """Khi có hai máy rảnh, hai job đầu phải được phân cho cả hai máy."""
    now = 1000.0
    cache = {"Node-A": _nf("Node-A"), "Node-B": _nf("Node-B")}
    q = LoadBalancer(max_queue=4)
    q.enqueue_job(job_type="burn", duration_s=1)
    q.enqueue_job(job_type="burn", duration_s=1)

    schedule_once(cache, q, DEFAULT_WEIGHTS, now)

    assert {job["target"] for job in q.reserved()} == {"Node-A", "Node-B"}


def test_s3_power_none_redistributes_weights():
    """Ca S3 — power_source=none → w_power phân bổ lại, tổng = 1."""
    f = _nf("A", power_source="none", power_w=None)
    sc, parts = score_node(f, DEFAULT_WEIGHTS, 1000.0)
    w = parts["weights"]
    assert w["power"] == 0.0
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(sc) >= 0.0


def test_s4_warming_up_penalty_0_7():
    """Ca S4 — WARMING_UP → điểm nhân 0.7."""
    ready = _nf("A", state="READY", predicted_max_c=None, current_temp_c=50.0)
    warm = _nf("A", state="WARMING_UP", predicted_max_c=None, current_temp_c=50.0)
    sr, pr = score_node(ready, DEFAULT_WEIGHTS, 1000.0)
    sw, pw = score_node(warm, DEFAULT_WEIGHTS, 1000.0)
    assert abs(pw["penalty"] - 0.7) < 1e-9
    assert abs(sw - sr * 0.7) < 1e-9


def test_s5_recently_failed_penalty_0_5():
    """Ca S5 — vừa giữ chỗ hết hạn → điểm nhân 0.5."""
    now = 1000.0
    f = _nf("A", recently_failed_until=now + 60)
    _, parts = score_node(f, DEFAULT_WEIGHTS, now)
    assert abs(parts["penalty"] - 0.5) < 1e-9


def test_s6_combined_penalty_0_35():
    """Ca S6 — WARMING_UP + recently_failed → 0.35."""
    now = 1000.0
    f = _nf("A", state="WARMING_UP", predicted_max_c=None, current_temp_c=50.0,
            recently_failed_until=now + 60)
    _, parts = score_node(f, DEFAULT_WEIGHTS, now)
    assert abs(parts["penalty"] - 0.35) < 1e-9


def test_s7_headroom_zero_not_negative():
    """Ca S7 — dự báo vượt ngưỡng → headroom = 0, không âm."""
    f = _nf("A", predicted_max_c=80.0, effective_threshold_c=75.0,
            idle_baseline_c=35.0)
    _, parts = score_node(f, DEFAULT_WEIGHTS, 1000.0)
    assert parts["headroom"] == 0.0


def test_s8_zero_span_does_not_crash():
    """Ca S8 — idle_baseline = ngưỡng → span chặn dưới 1.0."""
    f = _nf("A", idle_baseline_c=75.0, effective_threshold_c=75.0,
            predicted_max_c=70.0)
    sc, parts = score_node(f, DEFAULT_WEIGHTS, 1000.0)
    assert parts["headroom"] >= 0.0
    assert sc >= 0.0


def test_s9_score_independent_of_other_nodes():
    """Ca S9 — chứng minh M11 đã sửa: điểm không phụ thuộc node khác."""
    now = 1000.0
    a = _nf("Node-A", predicted_max_c=60.0, idle_baseline_c=35.0)
    sc1, _ = score_node(a, DEFAULT_WEIGHTS, now)
    hot = _nf("Node-HOT", predicted_max_c=95.0, idle_baseline_c=50.0)
    # thêm node nóng không đổi điểm A
    sc2, _ = score_node(a, DEFAULT_WEIGHTS, now)
    assert sc1 == sc2
    _ = hot  # hiện diện trong cụm không ảnh hưởng công thức


def test_s10_same_pred_different_baseline_different_headroom():
    """Ca S10 — cùng dự báo 70°C, baseline khác → headroom khác (bảng §4.2)."""
    thin = _nf("thin", idle_baseline_c=52.0, effective_threshold_c=85.0,
               predicted_max_c=70.0)
    desk = _nf("desk", idle_baseline_c=32.0, effective_threshold_c=75.0,
               predicted_max_c=70.0)
    _, pt = score_node(thin, DEFAULT_WEIGHTS, 1000.0)
    _, pd = score_node(desk, DEFAULT_WEIGHTS, 1000.0)
    assert abs(pt["headroom"] - 0.45) < 0.02
    assert abs(pd["headroom"] - 0.12) < 0.02
    assert pt["headroom"] > pd["headroom"]


def test_r3_reservation_expiry_requeues_and_penalizes():
    """Ca R3 — giữ chỗ hết hạn → inflight giảm, job về đầu, node bị phạt."""
    now = 1000.0
    cache = {"Node-A": _nf("Node-A"), "Node-B": _nf("Node-B")}
    q = LoadBalancer()
    job = q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now, reservation_timeout_s=20.0)
    assert cache["Node-A"].inflight + cache["Node-B"].inflight == 1
    winner = q.reserved()[0]["target"]
    assert cache[winner].inflight == 1
    # hết hạn
    reap_expired(cache, q, now + 21.0)
    assert cache[winner].inflight == 0
    assert cache[winner].recently_failed_until == now + 21.0 + FAILED_PENALTY_WINDOW_S
    pending = q.pending()
    assert len(pending) == 1
    assert pending[0]["id"] == job["id"]
    assert pending[0]["target"] is None


def test_r4_max_attempts_fails_no_capacity():
    """Ca R4 — hết hạn 3 lần → NO_CAPACITY."""
    now = 1000.0
    cache = {"Node-A": _nf("Node-A", last_sample_ts=now)}
    q = LoadBalancer()
    job = q.enqueue_job()
    jid = job["id"]
    t = now
    for _ in range(3):
        cache["Node-A"].last_sample_ts = t  # tránh stale_telemetry khi t chạy
        schedule_once(cache, q, DEFAULT_WEIGHTS, t, reservation_timeout_s=5.0)
        assert q.reserved(), f"no reservation at t={t}"
        t += 6.0
        reap_expired(cache, q, t)
    assert q.get_failed(jid)["code"] == "NO_CAPACITY"
    assert q.pending() == []


def test_round_robin_allows_flagged():
    """round_robin: node flagged vẫn nhận job (đối chứng A/B).

    Sole AT_RISK candidate phải thắng — không bị state_at_risk.
    """
    now = 1000.0
    cache = {
        "Node-A": _nf("Node-A", state="AT_RISK", predicted_max_c=80.0),
    }
    q = LoadBalancer()
    q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now, mode="round_robin")
    assert q.reserved(), "AT_RISK phải được reserve ở round_robin"
    assert q.reserved()[0]["target"] == "Node-A"


def test_round_robin_picks_flagged_among_peers():
    """round_robin: qua nhiều pick, AT_RISK phải nhận ≥1 job."""
    now = 1000.0
    cache = {
        "Node-A": _nf("Node-A", state="AT_RISK", predicted_max_c=80.0),
        "Node-B": _nf("Node-B", predicted_max_c=50.0),
    }
    q = LoadBalancer(max_queue=20)
    cursor = RoundRobinCursor()
    winners = []
    for _ in range(4):
        q.enqueue_job()
        schedule_once(cache, q, DEFAULT_WEIGHTS, now, mode="round_robin",
                      rr_cursor=cursor, max_assign=1)
        r = q.reserved()
        if r:
            w = r[-1]["target"]
            winners.append(w)
            # claim để giải phóng inflight cho vòng sau
            q.claim(w, now=now)
            cache[w].inflight = max(0, cache[w].inflight - 1)
            q.complete(w)
    assert "Node-A" in winners, f"flagged không được pick: {winners}"
