"""Kiểm hành vi hàng đợi + giữ chỗ. Bỏ _throttled (M14)."""
from balancer import LoadBalancer
from forecast_cache import NodeForecast
from scheduler import DEFAULT_WEIGHTS, schedule_once


def fill(lb, n=5):
    for _ in range(n):
        lb.enqueue_job()


def test_fifo_dispatch_and_stats():
    lb = LoadBalancer()
    j1 = lb.enqueue_job(duration_s=7, cores=2)
    fill(lb, 1)
    # Scheduler giữ chỗ rồi worker claim
    cache = {
        "Node-A": NodeForecast(
            node="Node-A", state="READY", predicted_max_c=50.0,
            current_temp_c=45.0, cpu_util=10.0, power_w=20.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=35.0, effective_threshold_c=75.0),
    }
    schedule_once(cache, lb, DEFAULT_WEIGHTS, 1000.0)
    got = lb.next_job("Node-A", now=1000.0)
    assert got["id"] == j1["id"] and got["duration_s"] == 7 and got["cores"] == 2
    stats = lb.stats()
    assert stats["dispatched"] == {"Node-A": 1}


def test_flagged_node_never_gets_jobs_via_scheduler():
    """thermal_aware: node flagged không được reserve."""
    lb = LoadBalancer()
    fill(lb)
    cache = {
        "Node-A": NodeForecast(
            node="Node-A", state="AT_RISK", predicted_max_c=80.0,
            current_temp_c=78.0, cpu_util=90.0, power_w=60.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=40.0, effective_threshold_c=75.0),
        "Node-B": NodeForecast(
            node="Node-B", state="READY", predicted_max_c=50.0,
            current_temp_c=45.0, cpu_util=10.0, power_w=20.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=35.0, effective_threshold_c=75.0),
    }
    schedule_once(cache, lb, DEFAULT_WEIGHTS, 1000.0)
    assert lb.next_job("Node-A", now=1000.0) is None
    assert lb.next_job("Node-B", now=1000.0) is not None


def test_queue_cap():
    lb = LoadBalancer(max_queue=2)
    assert lb.enqueue_job() is not None
    assert lb.enqueue_job() is not None
    assert lb.enqueue_job() is None


def test_cooler_headroom_wins_over_warmer_absolute_temp():
    """Thay test_warm_node_served_every_second_request (_throttled đã bỏ).

    Node ấm hơn tuyệt đối nhưng headroom cao hơn vẫn được reserve trước —
    công thức điểm quyết định, không còn throttle 1/2.
    """
    lb = LoadBalancer()
    fill(lb, 1)
    # Node-A: temp cao hơn nhưng baseline cũng cao → headroom lớn hơn
    # (laptop mỏng idle 52, pred 60, threshold 85 → headroom cao)
    # Node-B: desktop idle 32, pred 70, threshold 75 → headroom thấp
    cache = {
        "Node-A": NodeForecast(
            node="Node-A", state="READY", predicted_max_c=60.0,
            current_temp_c=58.0, cpu_util=10.0, power_w=25.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=52.0, effective_threshold_c=85.0,
            p_idle_w=15.0, p_max_w=65.0),
        "Node-B": NodeForecast(
            node="Node-B", state="READY", predicted_max_c=70.0,
            current_temp_c=50.0, cpu_util=10.0, power_w=25.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=32.0, effective_threshold_c=75.0,
            p_idle_w=15.0, p_max_w=65.0),
    }
    schedule_once(cache, lb, DEFAULT_WEIGHTS, 1000.0)
    reserved = lb.reserved()
    assert len(reserved) == 1
    assert reserved[0]["target"] == "Node-A"
    assert lb.next_job("Node-B", now=1000.0) is None
    assert lb.next_job("Node-A", now=1000.0) is not None


def test_targeted_job_only_goes_to_target():
    """Job đã có target sẵn (calibration) — chỉ node đó claim được."""
    lb = LoadBalancer()
    tj = lb.enqueue_job(target="Node-B")
    # Đã có target → không nằm pending; claim trực tiếp
    assert lb.next_job("Node-A", now=1000.0) is None
    assert lb.next_job("Node-B", now=1000.0)["id"] == tj["id"]


def test_r1_r2_reserved_only_claimable_by_target():
    """Ca R1/R2 — giữ chỗ Node-A: B→204/None, A→200."""
    lb = LoadBalancer()
    job = lb.enqueue_job()
    cache = {
        "Node-A": NodeForecast(
            node="Node-A", state="READY", predicted_max_c=50.0,
            current_temp_c=40.0, cpu_util=5.0, power_w=18.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=35.0, effective_threshold_c=75.0),
        "Node-B": NodeForecast(
            node="Node-B", state="READY", predicted_max_c=55.0,
            current_temp_c=45.0, cpu_util=5.0, power_w=18.0,
            power_source="sensor", last_sample_ts=1000.0,
            idle_baseline_c=35.0, effective_threshold_c=75.0),
    }
    schedule_once(cache, lb, DEFAULT_WEIGHTS, 1000.0)
    winner = lb.reserved()[0]["target"]
    other = "Node-B" if winner == "Node-A" else "Node-A"
    assert lb.next_job(other, now=1000.0) is None
    assert lb.next_job(winner, now=1000.0)["id"] == job["id"]
