"""Job event stream uses a dedicated rate bucket, not default 60/min."""
from __future__ import annotations

import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from rate_limit import DEFAULT_MAX, JOB_EVENTS_MAX
from room_assets import RUNTIME_ID, get_model
from server import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ROOM_CODE,
    DEFAULT_ROOM_PASSWORD,
    create_app,
    make_state,
    run_forecast_cycle,
)


def _state(tmp_path):
    return make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "no_model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
    )


def _join(client, name="Node-A", role="worker"):
    pw = (DEFAULT_ADMIN_PASSWORD if role == "admin"
          else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": DEFAULT_ROOM_CODE, "password": pw, "role": role}
    if role == "worker":
        body["node_name"] = name
        body["capabilities"] = {
            "cpu_cores": 4, "ram_gb": 8, "os": "t",
            "has_gpu": False, "agent_version": "t",
        }
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_ready(state, name, now=100.0, temp=45.0):
    for i in range(10):
        state.store.insert(name, now - 90 + i * 10, temp, None, 10.0, 20.0)
    run_forecast_cycle(state, now)
    model = get_model(state.settings.get()["model_id"])
    state.forecast_cache.patch(
        name, model_ready=True, model_id=model["model_id"],
        model_sha256=model["sha256"], model_generation=state.llm_generation,
        runtime_id=RUNTIME_ID)


def _claim_chat(client, state, admin_tok, worker_tok, now=100.0):
    r = client.post(
        "/chat", headers=_auth(admin_tok),
        json={"prompt": "hello", "max_tokens": 64, "stream": True})
    assert r.status_code == 202, r.text
    from server import run_scheduler_cycle
    run_scheduler_cycle(state, now)
    nxt = client.get("/jobs/next?wait=0", headers=_auth(worker_tok))
    assert nxt.status_code == 200, nxt.text
    return nxt.json()


def test_job_events_allow_more_than_default_quota(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    worker = _join(c, "Node-A")["token"]
    _seed_ready(state, "Node-A")
    job = _claim_chat(c, state, admin, worker)
    jid = job["id"]
    attempt = job["attempt_id"]

    # DEFAULT_MAX + 5 would trip the old shared bucket; must stay 202.
    n = DEFAULT_MAX + 5
    assert n < JOB_EVENTS_MAX
    for seq in range(n):
        r = c.post(
            f"/jobs/{jid}/events", headers=_auth(worker),
            json={"attempt_id": attempt, "seq": seq, "delta": "x"})
        assert r.status_code == 202, (seq, r.text)


def test_default_bucket_unaffected_by_job_events(tmp_path):
    """Events use job_events bucket; default still caps other endpoints."""
    from rate_limit import TokenRateLimiter, DEFAULT_WINDOW_S

    lim = TokenRateLimiter()
    tok = "abc"
    now = 1_000.0
    for _ in range(DEFAULT_MAX):
        lim.check("default", tok, max_hits=DEFAULT_MAX,
                  window_s=DEFAULT_WINDOW_S, now=now)
    # job_events traffic must not fill default
    for i in range(100):
        lim.check("job_events", tok, max_hits=JOB_EVENTS_MAX,
                  window_s=60.0, now=now + i * 0.001)
    try:
        lim.check("default", tok, max_hits=DEFAULT_MAX,
                  window_s=DEFAULT_WINDOW_S, now=now)
        raised = False
    except Exception:
        raised = True
    assert raised is True
