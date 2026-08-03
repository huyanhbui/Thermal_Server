"""P1: /jobs/next không chờ mutation_section 60s cố định."""
from __future__ import annotations

import os
import threading
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state, _run_room_lifecycle


CAPS = {"cpu_cores": 2, "ram_gb": 4, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_jobs_next_wait0_returns_quickly_when_lifecycle_held(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    c = TestClient(create_app(state))
    assert c.post("/api/room/bootstrap", json={
        "display_name": "A",
        "worker_password": "worker-pass-ok12",
        "admin_password": "admin-pass-ok12",
    }).status_code == 200
    admin = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "admin-pass-ok12",
        "role": "admin",
        "node_name": "Adm",
        "capabilities": CAPS,
    }).json()["token"]
    wtok = c.post("/join", json={
        "room_code": state.room.room_code,
        "password": "worker-pass-ok12",
        "role": "worker",
        "node_name": "W1",
        "capabilities": CAPS,
    }).json()["token"]

    hold = threading.Event()
    release = threading.Event()

    def finish():
        hold.set()
        release.wait(timeout=10)

    def closer():
        now = time.time()
        _run_room_lifecycle(
            state, reason="close", now=now,
            finish_fn=lambda: (
                finish(),
                state.room.lifecycle_close(now=now, ip="testclient"),
            )[-1])

    t = threading.Thread(target=closer, daemon=True)
    t.start()
    assert hold.wait(timeout=5)
    t0 = time.monotonic()
    r = c.get("/jobs/next?wait=0", headers=_auth(wtok))
    elapsed = time.monotonic() - t0
    release.set()
    t.join(timeout=5)
    # Không treo ~60s; wait=0 → 204 (timeout mutation) hoặc 401 nếu revoke kịp
    assert r.status_code in (204, 401), r.text
    assert elapsed < 5.0, f"treo quá lâu: {elapsed:.2f}s"
