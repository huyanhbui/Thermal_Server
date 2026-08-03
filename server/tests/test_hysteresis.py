"""Ca H1–H5: băng trễ gắn/gỡ cờ (docs/04 §9). Chỉ cần ForecastCache logic."""
from forecast_cache import (
    HYSTERESIS_C, MIN_DWELL_S, NodeForecast, apply_hysteresis)

THRESHOLD = 75.0

def _prev(state, changed_at, flagged_since=None):
    return NodeForecast(
        node="N", state=state, state_changed_at=changed_at,
        flagged_since=flagged_since, predicted_max_c=None)

def test_h1_cross_above_threshold_flags():
    # H1: 74 → 76 → gắn cờ
    prev = _prev("READY", changed_at=0.0)
    state, changed, _ = apply_hysteresis(
        prev, base_state="READY", pred=76.0,
        threshold_c=THRESHOLD, now=100.0)
    assert state == "AT_RISK"
    assert changed == 100.0

def test_h2_inside_band_stays_flagged():
    # H2: 76 → 74 → vẫn gắn (74 > 72)
    prev = _prev("AT_RISK", changed_at=50.0, flagged_since=50.0)
    state, changed, _ = apply_hysteresis(
        prev, base_state="READY", pred=74.0,
        threshold_c=THRESHOLD, now=100.0)
    assert state == "AT_RISK"
    assert changed == 50.0
    assert 74.0 > THRESHOLD - HYSTERESIS_C

def test_h3_below_clear_band_unflags():
    # H3: 76 → 71 → gỡ cờ (đã đủ dwell)
    prev = _prev("AT_RISK", changed_at=50.0, flagged_since=50.0)
    state, changed, _ = apply_hysteresis(
        prev, base_state="READY", pred=71.0,
        threshold_c=THRESHOLD, now=50.0 + MIN_DWELL_S + 1)
    assert state == "READY"
    assert changed == 50.0 + MIN_DWELL_S + 1

def test_h4_rapid_oscillation_changes_only_once():
    # H4: 74→76→74→76 trong 10s → đổi trạng thái đúng một lần
    t0 = 100.0
    prev = _prev("READY", changed_at=0.0)
    s1, c1, _ = apply_hysteresis(
        prev, base_state="READY", pred=76.0,
        threshold_c=THRESHOLD, now=t0)
    assert s1 == "AT_RISK"
    prev = _prev("AT_RISK", changed_at=c1, flagged_since=c1)
    s2, c2, _ = apply_hysteresis(
        prev, base_state="READY", pred=74.0,
        threshold_c=THRESHOLD, now=t0 + 3)
    assert s2 == "AT_RISK" and c2 == c1  # band + dwell
    prev = _prev("AT_RISK", changed_at=c2, flagged_since=c1)
    s3, c3, _ = apply_hysteresis(
        prev, base_state="READY", pred=76.0,
        threshold_c=THRESHOLD, now=t0 + 6)
    assert s3 == "AT_RISK" and c3 == c1  # still same flag event
    # Only one transition into AT_RISK occurred.
    assert c1 == t0

def test_h5_clear_after_dwell():
    # H5: 76, chờ 40s, 71 → gỡ cờ
    prev = _prev("AT_RISK", changed_at=100.0, flagged_since=100.0)
    state, changed, _ = apply_hysteresis(
        prev, base_state="READY", pred=71.0,
        threshold_c=THRESHOLD, now=140.0)
    assert state == "READY"
    assert changed == 140.0

def test_dwell_blocks_clear_too_soon():
    prev = _prev("AT_RISK", changed_at=100.0, flagged_since=100.0)
    state, _, _ = apply_hysteresis(
        prev, base_state="READY", pred=71.0,
        threshold_c=THRESHOLD, now=110.0)  # only 10s
    assert state == "AT_RISK"

def test_dwell_blocks_reflag_too_soon_after_clear():
    # Clear at t=100, then pred crosses threshold at t=110 → still READY.
    cleared = _prev("READY", changed_at=100.0, flagged_since=None)
    state, changed, reason = apply_hysteresis(
        cleared, base_state="READY", pred=76.0,
        threshold_c=THRESHOLD, now=110.0)
    assert state == "READY"
    assert changed == 100.0
    assert "dwell block" in reason

def test_reflag_allowed_after_dwell():
    # Same clear at t=100; at t=131 (>= MIN_DWELL) may flag again.
    cleared = _prev("READY", changed_at=100.0, flagged_since=None)
    state, changed, _ = apply_hysteresis(
        cleared, base_state="READY", pred=76.0,
        threshold_c=THRESHOLD, now=100.0 + MIN_DWELL_S + 1)
    assert state == "AT_RISK"
    assert changed == 100.0 + MIN_DWELL_S + 1
