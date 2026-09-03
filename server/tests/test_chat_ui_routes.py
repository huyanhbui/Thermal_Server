"""Behavior contracts for raised chat quotas and UI path aliases."""
from __future__ import annotations

import os

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

from balancer import LoadBalancer
from rate_limit import CHAT_MAX
from server import create_app, make_state


def _state(tmp_path):
    return make_state(
        db_path=":memory:", model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"), bootstrap_open=True,
    )


def test_default_chat_queue_holds_thirty_two_jobs():
    assert LoadBalancer().max_queue == 32


def test_chat_rate_limit_allows_sixty_per_minute():
    assert CHAT_MAX == 60


def test_ui_path_aliases_serve_the_same_dashboard(tmp_path):
    client = TestClient(create_app(_state(tmp_path)))
    bodies = []
    for path in ("/", "/landing", "/login", "/app"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "text/html" in response.headers.get("content-type", "")
        bodies.append(response.text)
    assert bodies[0] == bodies[1] == bodies[2] == bodies[3]
    assert "Distributed chat" in bodies[0]


def test_join_redirect_still_lands_on_root_with_code(tmp_path):
    client = TestClient(create_app(_state(tmp_path)))
    response = client.get("/join?code=THERMAL-ABCD", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/?code=")
