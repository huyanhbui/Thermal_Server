"""Cô lập job/chat theo vòng đời phòng — không rò sang phòng mới."""
import os

os.environ["POC_NO_BACKGROUND"] = "1"
os.environ["POC_HOST_LLM_STUB"] = "1"

from fastapi.testclient import TestClient

from server import create_app, make_state, run_forecast_cycle, run_scheduler_cycle


CAPS = {"cpu_cores": 4, "ram_gb": 8, "os": "t",
        "has_gpu": False, "agent_version": "t"}


def _open_client(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "m.pkl"),
        settings_path=str(tmp_path / "s.json"),
        esg_path=str(tmp_path / "e.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )
    return TestClient(create_app(state)), state


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _bootstrap(c, worker="worker-pass-ok12", admin="admin-pass-ok12",
               name="Phong-A", headers=None):
    body = {
        "display_name": name,
        "worker_password": worker,
        "admin_password": admin,
    }
    r = c.post("/api/room/bootstrap", json=body, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["room"]


def _join_worker(c, code, password, node):
    r = c.post("/join", json={
        "room_code": code,
        "password": password,
        "role": "worker",
        "node_name": node,
        "capabilities": CAPS,
    })
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _join_admin(c, code, password):
    r = c.post("/join", json={
        "room_code": code,
        "password": password,
        "role": "admin",
    })
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _seed_ready(state, name, now=100.0, temp=45.0):
    from room_assets import RUNTIME_ID, get_model

    for i in range(10):
        state.store.insert(name, now - 90 + i * 10, temp, None, 10.0, 20.0)
    run_forecast_cycle(state, now)
    model_id = state.settings.get()["model_id"]
    state.forecast_cache.patch(
        name, model_ready=True, model_id=model_id,
        model_sha256=get_model(model_id)["sha256"],
        model_generation=state.llm_generation, runtime_id=RUNTIME_ID,
    )


def test_close_purges_pending_chat_not_claimed_by_new_room(tmp_path):
    """Enqueue chat phòng A → close → bootstrap B → node mới không nhận job cũ."""
    c, state = _open_client(tmp_path)
    room = _bootstrap(c)
    code = room["code"]
    admin = _join_admin(c, code, "admin-pass-ok12")
    wtok = _join_worker(c, code, "worker-pass-ok12", "Node-A")
    _seed_ready(state, "Node-A", now=100.0)

    chat = c.post("/chat", headers=_auth(admin),
                  json={"prompt": "PROMPT-CU-PHONG-A", "max_tokens": 32})
    assert chat.status_code == 202
    old_jid = chat.json()["job_id"]
    assert any(j["id"] == old_jid for j in state.balancer.pending())

    close = c.post("/api/room/close", headers=_auth(admin))
    assert close.status_code == 200

    # Hàng đợi và active phải trống ngay sau close
    assert state.balancer.pending() == []
    assert state.balancer.reserved() == []
    assert state.balancer.list_active() == []
    old_chat = state.chat.get(old_jid)
    assert old_chat is None or old_chat["status"] == "error"

    room_b = _bootstrap(c, worker="worker-pass-ok99",
                        admin="admin-pass-ok99", name="Phong-B")
    new_tok = _join_worker(c, room_b["code"], "worker-pass-ok99",
                           "Node-Phong-Moi")
    _seed_ready(state, "Node-Phong-Moi", now=200.0)
    run_scheduler_cycle(state, 200.0)

    claimed = c.get("/jobs/next?wait=0", headers=_auth(new_tok))
    assert claimed.status_code == 204, (
        f"Node phòng mới không được nhận job cũ, got {claimed.status_code} "
        f"{claimed.text}")
    # Prompt cũ không còn trong bất kỳ job nào
    for j in state.balancer.pending() + state.balancer.reserved():
        assert j.get("prompt") != "PROMPT-CU-PHONG-A"
        assert j["id"] != old_jid
    for _, j in state.balancer.list_active():
        assert j["id"] != old_jid


def test_close_purges_reserved_and_active_jobs(tmp_path):
    """Job reserved + active cũng bị hủy khi đóng phòng."""
    c, state = _open_client(tmp_path)
    room = _bootstrap(c)
    code = room["code"]
    admin = _join_admin(c, code, "admin-pass-ok12")
    wtok = _join_worker(c, code, "worker-pass-ok12", "Node-A")
    _seed_ready(state, "Node-A", now=100.0)

    # Burn pending → schedule → reserved (chưa claim)
    burn = state.balancer.enqueue_job(duration_s=10, cores=1, job_type="burn")
    assert burn is not None
    burn_id = burn["id"]
    run_scheduler_cycle(state, 100.0)
    reserved = [j for j in state.balancer.reserved() if j["id"] == burn_id]
    assert reserved, "burn phải được reserve trước khi close"

    # Chat active trên Node-B riêng (tránh claim nhầm burn trên Node-A)
    wtok_b = _join_worker(c, code, "worker-pass-ok12", "Node-B")
    _seed_ready(state, "Node-B", now=100.0)
    chat = c.post("/chat", headers=_auth(admin),
                  json={"prompt": "ACTIVE-CU", "max_tokens": 16})
    chat_id = chat.json()["job_id"]
    assert state.balancer.reserve(chat_id, "Node-B", until=200.0, now=100.0)
    claimed = state.balancer.claim("Node-B", now=100.0)
    assert claimed is not None
    assert claimed["id"] == chat_id
    state.chat.mark_running(chat_id, "Node-B", now=100.0)
    assert state.balancer.list_active()
    assert any(j["id"] == burn_id for j in state.balancer.reserved())

    close = c.post("/api/room/close", headers=_auth(admin))
    assert close.status_code == 200

    assert state.balancer.pending() == []
    assert state.balancer.reserved() == []
    assert state.balancer.list_active() == []
    # Prompt không còn trên job failed snapshot
    failed_chat = state.balancer.get_failed(chat_id)
    assert failed_chat is not None
    assert failed_chat["code"] == "ROOM_CLOSED"

    room_b = _bootstrap(c, worker="worker-pass-ok99",
                        admin="admin-pass-ok99", name="Phong-B")
    new_tok = _join_worker(c, room_b["code"], "worker-pass-ok99",
                           "Node-Phong-Moi")
    _seed_ready(state, "Node-Phong-Moi", now=300.0)
    run_scheduler_cycle(state, 300.0)
    r = c.get("/jobs/next?wait=0", headers=_auth(new_tok))
    assert r.status_code == 204
    # Token cũ chết
    assert c.get("/jobs/next?wait=0",
                 headers=_auth(wtok)).status_code in (401, 403)


def test_password_rotate_also_purges_queue(tmp_path):
    """Đổi mật khẩu qua bootstrap thu hồi token và dọn hàng đợi."""
    c, state = _open_client(tmp_path)
    room = _bootstrap(c)
    code = room["code"]
    admin = _join_admin(c, code, "admin-pass-ok12")
    _join_worker(c, code, "worker-pass-ok12", "Node-A")
    _seed_ready(state, "Node-A")

    chat = c.post("/chat", headers=_auth(admin),
                  json={"prompt": "SECRET-PROMPT", "max_tokens": 8})
    old_jid = chat.json()["job_id"]
    assert state.balancer.pending()

    r = c.post("/api/room/bootstrap",
               headers=_auth(admin),
               json={
                   "display_name": "Phong-Moi",
                   "worker_password": "worker-pass-ok99",
                   "admin_password": "admin-pass-ok99",
               })
    assert r.status_code == 200
    assert state.balancer.pending() == []
    assert state.balancer.reserved() == []
    assert state.balancer.list_active() == []
    old = state.chat.get(old_jid)
    assert old is None or old["status"] == "error"
    for j in state.balancer.pending() + state.balancer.reserved():
        assert "SECRET-PROMPT" not in str(j.get("prompt", ""))


def test_reopen_bootstrap_purges_jobs(tmp_path):
    c, state = _open_client(tmp_path)
    room = _bootstrap(c)
    code = room["code"]
    admin = _join_admin(c, code, "admin-pass-ok12")
    _join_worker(c, code, "worker-pass-ok12", "Node-A")
    _seed_ready(state, "Node-A")
    c.post("/chat", headers=_auth(admin),
           json={"prompt": "REOPEN-CU", "max_tokens": 8})
    assert state.balancer.pending()

    r = c.post("/api/room/reopen-bootstrap")
    assert r.status_code == 200
    assert state.balancer.pending() == []
    assert state.balancer.list_active() == []
