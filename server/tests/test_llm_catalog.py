"""Catalog LLM ADR-006 — list/settings/join theo model_id."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from room_assets import (
    DEFAULT_MODEL_ID,
    MODEL_CATALOG,
    UnknownModelError,
    get_model,
    list_models,
    room_config_llm,
)
from server import (DEFAULT_ADMIN_PASSWORD, DEFAULT_ROOM_CODE,
                    DEFAULT_ROOM_PASSWORD, create_app, make_state)
from settings import Settings


def _state(tmp_path):
    return make_state(db_path=":memory:",
                      model_path=str(tmp_path / "no_model.pkl"),
                      settings_path=str(tmp_path / "settings.json"),
                      esg_path=str(tmp_path / "esg.json"))


def _join(client, name="Node-A", role="worker"):
    pw = (DEFAULT_ADMIN_PASSWORD if role == "admin"
          else DEFAULT_ROOM_PASSWORD)
    body = {"room_code": DEFAULT_ROOM_CODE,
            "password": pw, "role": role}
    if role == "worker":
        body["node_name"] = name
        body["capabilities"] = {"cpu_cores": 4, "ram_gb": 8, "os": "t",
                                "has_gpu": False, "agent_version": "t"}
    r = client.post("/join", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_room_assets_catalog_contains_four_models():
    ids = {m["model_id"] for m in list_models()}
    assert ids == {
        "qwen2.5-0.5b-instruct-q4_k_m",
        "qwen3-0.6b-q4_k_m",
        "qwen3.5-2b-q4_k_m",
        "gemma-4-e2b-it-q4_k_m",
    }
    assert "qwen2.5-1.5b-instruct-q4_k_m" not in ids
    assert DEFAULT_MODEL_ID in MODEL_CATALOG
    q35 = get_model("qwen3.5-2b-q4_k_m")
    assert q35["filename"].endswith(".gguf")
    assert len(q35["sha256"]) == 64
    gem = get_model("gemma-4-e2b-it-q4_k_m")
    assert "gemma-4-E2B" in gem["filename"]


def test_settings_rejects_unknown_model(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    r = c.post("/api/settings", headers=_auth(admin),
               json={"model_id": "not-a-real-model"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_MODEL"


def test_join_room_config_follows_selected_model(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    mid = "qwen3.5-2b-q4_k_m"
    r = c.post("/api/settings", headers=_auth(admin),
               json={"model_id": mid})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["model_id"] == mid

    data = _join(c, "Node-B")
    cfg = data["room_config"]
    assert cfg["model_id"] == mid
    assert cfg["model_filename"] == MODEL_CATALOG[mid]["filename"]
    assert cfg["model_sha256"].upper() == MODEL_CATALOG[mid]["sha256"]
    assert cfg["model_generation"] == 1
    assert "Qwen3.5-2B" in cfg["model_url"] or "Qwen_Qwen3.5" in cfg["model_url"]


def test_api_models_lists_catalog_and_selected(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    r = c.get("/api/models", headers=_auth(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["selected"] == DEFAULT_MODEL_ID
    assert len(body["models"]) == 4
    worker = _join(c, "Node-A")["token"]
    denied = c.get("/api/models", headers=_auth(worker))
    assert denied.status_code == 403


def test_state_exposes_llm_model_fields(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    st = c.get("/api/state", headers=_auth(admin)).json()
    assert st["llm_model_id"] == DEFAULT_MODEL_ID
    assert "Qwen2.5-0.5B" in st["llm_model_display"]
    # Worker compact vẫn thấy llm_model_id để đổi model.
    tok = _join(c, "Node-A")["token"]
    w = c.get("/api/state", headers=_auth(tok)).json()
    assert w["llm_model_id"] == DEFAULT_MODEL_ID
    assert "llm_model_display" not in w


def test_settings_model_id_persists(tmp_path):
    p = str(tmp_path / "settings.json")
    s = Settings(p)
    assert s.get()["model_id"] == DEFAULT_MODEL_ID
    s.set_model_id("gemma-4-e2b-it-q4_k_m")
    assert Settings(p).get()["model_id"] == "gemma-4-e2b-it-q4_k_m"


def test_get_model_unknown_raises():
    try:
        get_model("nope")
        assert False, "expected UnknownModelError"
    except UnknownModelError:
        pass


def test_get_model_none_falls_back_to_default():
    m = get_model(None)
    assert m["model_id"] == DEFAULT_MODEL_ID


def test_get_model_empty_or_whitespace_raises():
    for bad in ("", "   ", "\t"):
        try:
            get_model(bad)
            assert False, f"expected UnknownModelError for {bad!r}"
        except UnknownModelError:
            pass


def test_settings_rejects_whitespace_model_id(tmp_path):
    state = _state(tmp_path)
    c = TestClient(create_app(state))
    admin = _join(c, role="admin")["token"]
    r = c.post("/api/settings", headers=_auth(admin),
               json={"model_id": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_MODEL"


def test_dirty_settings_model_id_join_uses_default(tmp_path):
    """File settings model_id lạ → sanitize; join 201 + room_config default."""
    p = tmp_path / "settings.json"
    p.write_text('{"model_id": "not-in-catalog-ever"}', encoding="utf-8")
    state = make_state(db_path=":memory:",
                       model_path=str(tmp_path / "no_model.pkl"),
                       settings_path=str(p),
                       esg_path=str(tmp_path / "esg.json"))
    assert state.settings.get()["model_id"] == DEFAULT_MODEL_ID
    c = TestClient(create_app(state))
    data = _join(c, "Node-Dirty")
    assert data["room_config"]["model_id"] == DEFAULT_MODEL_ID


def test_inmemory_invalid_model_id_join_still_201(tmp_path):
    """Bỏ qua sanitize: _selected_model_id fallback, không 500."""
    state = _state(tmp_path)
    state.settings._data["model_id"] = "ghost-model"
    c = TestClient(create_app(state))
    data = _join(c, "Node-Ghost")
    assert data["room_config"]["model_id"] == DEFAULT_MODEL_ID


def test_room_config_default_has_filename():
    cfg = room_config_llm()
    assert cfg["model_filename"] == "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
    assert cfg["model_id"] == DEFAULT_MODEL_ID
