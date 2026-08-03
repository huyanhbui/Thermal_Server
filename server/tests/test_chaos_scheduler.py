"""Ca hỗn loạn scheduler — docs/11 §5 X2 + R5/R6."""
from forecast_cache import NodeForecast
from balancer import LoadBalancer
from scheduler import DEFAULT_WEIGHTS, schedule_once, reap_expired


def _ready(name, **kw):
    d = dict(
        node=name, state="READY", predicted_max_c=55.0, current_temp_c=45.0,
        cpu_util=10.0, power_w=20.0, power_source="sensor", inflight=0,
        max_concurrent=1, model_ready=True, last_sample_ts=1000.0,
        idle_baseline_c=35.0, effective_threshold_c=75.0,
    )
    d.update(kw)
    return NodeForecast(**d)


def test_x2_worker_dies_mid_job_reassigned():
    """Ca X2 — worker nhận job rồi chết → hết hạn → máy khác nhận."""
    now = 1000.0
    cache = {
        "Node-A": _ready("Node-A", predicted_max_c=50.0),
        "Node-B": _ready("Node-B", predicted_max_c=60.0),
    }
    q = LoadBalancer()
    job = q.enqueue_job(job_type="chat")
    jid = job["id"]
    schedule_once(cache, q, DEFAULT_WEIGHTS, now, reservation_timeout_s=20.0)
    winner = q.reserved()[0]["target"]
    # Worker "chết" — không claim
    other = "Node-B" if winner == "Node-A" else "Node-A"
    assert q.claim(other, now=now) is None
    # Hết hạn giữ chỗ
    reap_expired(cache, q, now + 21.0)
    assert q.pending()[0]["id"] == jid
    # Chấm điểm lại — có thể cùng hoặc khác node
    cache[winner].last_sample_ts = now + 21.0
    cache[other].last_sample_ts = now + 21.0
    # Phạt winner → other dễ thắng hơn nếu điểm gần nhau
    schedule_once(cache, q, DEFAULT_WEIGHTS, now + 21.0,
                  reservation_timeout_s=20.0)
    reserved = q.reserved()
    assert reserved and reserved[0]["id"] == jid
    # Người dùng vẫn nhận được trả lời: job còn sống, được gán lại
    second = reserved[0]["target"]
    claimed = q.claim(second, now=now + 21.0)
    assert claimed["id"] == jid


def test_r5_job_complete_decrements_inflight():
    """Ca R5 — job hoàn thành → inflight giảm."""
    now = 1000.0
    cache = {"Node-A": _ready("Node-A")}
    q = LoadBalancer()
    job = q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    assert cache["Node-A"].inflight == 1
    claimed = q.claim("Node-A", now=now)
    assert claimed["id"] == job["id"]
    # complete phía balancer; caller giảm inflight (như /jobs/result)
    q.complete("Node-A", job["id"])
    cache["Node-A"].inflight = max(0, cache["Node-A"].inflight - 1)
    assert cache["Node-A"].inflight == 0


def test_r6_kick_releases_reservation_immediately():
    """Ca R6 — release reservation chưa claim → job về hàng đợi ngay."""
    now = 1000.0
    cache = {"Node-A": _ready("Node-A"), "Node-B": _ready("Node-B")}
    q = LoadBalancer()
    job = q.enqueue_job()
    schedule_once(cache, q, DEFAULT_WEIGHTS, now)
    winner = q.reserved()[0]["target"]
    released = q.release_reservations_for(winner)
    assert job["id"] in released
    assert q.pending()[0]["id"] == job["id"]
    assert q.pending()[0]["target"] is None
