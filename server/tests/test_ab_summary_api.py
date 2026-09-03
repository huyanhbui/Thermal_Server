"""Unit tests for /api/ab_summary and compute_ab_summary."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

import pytest
from fastapi.testclient import TestClient

from server import compute_ab_summary, create_app, make_state
from store import TelemetryStore


def test_compute_ab_summary_empty():
    result = compute_ab_summary([])
    assert result["ok"] is True
    assert result["thermal_aware"]["total_jobs"] == 0
    assert result["thermal_aware"]["max_temp_c"] is None
    assert result["thermal_aware"]["energy_per_token_j"] is None
    assert result["thermal_aware"]["total_energy_j"] == 0.0
    assert result["thermal_aware"]["total_tokens_out"] == 0

    assert result["round_robin"]["total_jobs"] == 0
    assert result["round_robin"]["max_temp_c"] is None
    assert result["round_robin"]["energy_per_token_j"] is None

    assert result["comparison"]["energy_savings_pct"] is None
    assert result["comparison"]["temp_reduction_c"] is None


def test_compute_ab_summary_mixed_data():
    events = [
        {
            "ts": 10.0,
            "node": "Node-A",
            "event_type": "job_completed",
            "detail": {
                "scheduler_mode": "thermal_aware",
                "peak_temp_c": 65.4,
                "energy_j": 500.0,
                "tokens_out": 250,
            },
        },
        {
            "ts": 20.0,
            "node": "Node-B",
            "event_type": "job_complete",
            "detail": {
                "scheduler_mode": "thermal_aware",
                "peak_temp_c": 68.2,
                "energy_j": 700.0,
                "tokens_out": 350,
            },
        },
        {
            "ts": 30.0,
            "node": "Node-C",
            "event_type": "job_completed",
            "detail": {
                "scheduler_mode": "round_robin",
                "peak_temp_c": 79.5,
                "energy_j": 1200.0,
                "tokens_out": 400,
            },
        },
        {
            "ts": 40.0,
            "node": "Node-D",
            "event_type": "job_completed",
            "detail": {
                "scheduler_mode": "round_robin",
                "peak_temp_c": 82.1,
                "energy_j": 1800.0,
                "tokens_out": 600,
            },
        },
        {
            "ts": 50.0,
            "node": "Node-A",
            "event_type": "flagged",
            "detail": {"pred": 76.0},
        },
    ]

    result = compute_ab_summary(events)
    assert result["ok"] is True

    # Thermal-Aware stats:
    # jobs: 2
    # peak temps: [65.4, 68.2] -> max 68.2
    # total energy: 500 + 700 = 1200 J
    # total tokens: 250 + 350 = 600
    # energy_per_token: 1200 / 600 = 2.0 J/token
    ta = result["thermal_aware"]
    assert ta["total_jobs"] == 2
    assert ta["max_temp_c"] == 68.2
    assert ta["total_energy_j"] == 1200.0
    assert ta["total_tokens_out"] == 600
    assert ta["energy_per_token_j"] == 2.0

    # Round-Robin stats:
    # jobs: 2
    # peak temps: [79.5, 82.1] -> max 82.1
    # total energy: 1200 + 1800 = 3000 J
    # total tokens: 400 + 600 = 1000
    # energy_per_token: 3000 / 1000 = 3.0 J/token
    rr = result["round_robin"]
    assert rr["total_jobs"] == 2
    assert rr["max_temp_c"] == 82.1
    assert rr["total_energy_j"] == 3000.0
    assert rr["total_tokens_out"] == 1000
    assert rr["energy_per_token_j"] == 3.0

    # Comparison:
    # energy savings: (3.0 - 2.0) / 3.0 * 100 = 33.3%
    # temp reduction: 82.1 - 68.2 = 13.9 C
    comp = result["comparison"]
    assert comp["energy_savings_pct"] == 33.3
    assert comp["temp_reduction_c"] == 13.9


def test_ab_summary_endpoint_http():
    state = make_state(db_path=":memory:")
    # Insert some sample events into store
    state.store.insert_esg_event(
        10.0, "Node-1", "job_completed",
        {
            "scheduler_mode": "thermal_aware",
            "peak_temp_c": 62.0,
            "energy_j": 200.0,
            "tokens_out": 100,
        },
    )
    state.store.insert_esg_event(
        20.0, "Node-2", "job_completed",
        {
            "scheduler_mode": "round_robin",
            "peak_temp_c": 75.0,
            "energy_j": 350.0,
            "tokens_out": 100,
        },
    )

    app = create_app(state)
    client = TestClient(app)

    response = client.get("/api/ab_summary")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["thermal_aware"]["total_jobs"] == 1
    assert data["thermal_aware"]["max_temp_c"] == 62.0
    assert data["thermal_aware"]["energy_per_token_j"] == 2.0

    assert data["round_robin"]["total_jobs"] == 1
    assert data["round_robin"]["max_temp_c"] == 75.0
    assert data["round_robin"]["energy_per_token_j"] == 3.5

    assert data["comparison"]["temp_reduction_c"] == 13.0
    assert data["comparison"]["energy_savings_pct"] == pytest.approx(42.9, abs=0.1)
