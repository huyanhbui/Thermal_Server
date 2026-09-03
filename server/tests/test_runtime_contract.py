"""Hợp đồng runtime Host: revision API, chính sách mật khẩu và single-instance."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["POC_NO_BACKGROUND"] = "1"

from fastapi.testclient import TestClient

import server as server_module
from server import (
    API_REVISION,
    _local_agent_executable,
    _legacy_database_paths,
    _local_agent_config_path,
    _restore_local_agent,
    _invite_urls,
    _runtime_data_path,
    create_app,
    make_state,
)


def _state(tmp_path):
    return make_state(
        db_path=":memory:", model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"), bootstrap_open=True,
    )


def test_version_endpoint_exposes_the_dashboard_contract_revision(tmp_path):
    client = TestClient(create_app(_state(tmp_path)))

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"api_revision": API_REVISION}


def test_explicit_data_directory_is_an_operator_choice_not_an_auto_merge(monkeypatch):
    """THERMAL_DATA_DIR đã chỉ rõ DB chuẩn thì không quét legacy cạnh repo."""
    monkeypatch.setenv("THERMAL_DATA_DIR", r"C:\ProgramData\ThermalOrchestrator\shared")
    assert _legacy_database_paths() == ()


def test_explicit_data_directory_moves_relative_operational_config(monkeypatch):
    monkeypatch.setenv("THERMAL_DATA_DIR", r"C:\ProgramData\ThermalOrchestrator\shared")
    assert _runtime_data_path("settings.json") == (
        r"C:\ProgramData\ThermalOrchestrator\shared\settings.json")
    assert _runtime_data_path("model.pkl") == (
        r"C:\ProgramData\ThermalOrchestrator\shared\model.pkl")
    assert _runtime_data_path("nested/settings.json") == "nested/settings.json"


def test_make_state_loads_forecaster_model_from_thermal_data_dir(
        tmp_path, monkeypatch):
    """Installer đặt THERMAL_DATA_DIR; model.pkl phải cạnh telemetry, không theo CWD."""
    data = tmp_path / "shared"
    data.mkdir()
    monkeypatch.setenv("THERMAL_DATA_DIR", str(data))
    monkeypatch.chdir(tmp_path)
    state = make_state(db_path=":memory:", bootstrap_open=True)
    assert state.forecaster.model_loaded is False
    # Relative default remaps; absolute fixture path must stay untouched.
    other = tmp_path / "fixture" / "model.pkl"
    other.parent.mkdir()
    abs_state = make_state(
        db_path=":memory:", model_path=str(other), bootstrap_open=True)
    assert abs_state.forecaster.model_loaded is False
    from server import _runtime_data_path
    assert _runtime_data_path("model.pkl") == str(data / "model.pkl")


def test_one_exe_starts_host_with_the_shared_programdata_directory():
    script = (Path(__file__).parents[2] / "scripts"
              / "publish_orchestrator.ps1").read_text(encoding="utf-8-sig")
    assert r"THERMAL_DATA_DIR=%ProgramData%\ThermalOrchestrator\shared" in script
    assert "$host =" not in script
    assert "$hostDir =" in script
    assert r"..\..\host" in script
    assert '"ThermalOrchestrator.pdb"' in script
    assert "Remove-Item -LiteralPath $symbolFile -Force" in script


def test_packaged_host_finds_nodeagent_at_the_payload_agent_root(
        tmp_path, monkeypatch):
    """Payload EXE đặt NodeAgent tại versions/<v>/agent, không phải cây build."""
    host_file = tmp_path / "versions" / "test" / "host" / "server.py"
    agent_file = tmp_path / "versions" / "test" / "agent" / "NodeAgent.exe"
    host_file.parent.mkdir(parents=True)
    agent_file.parent.mkdir(parents=True)
    host_file.write_text("# test", encoding="utf-8")
    agent_file.write_bytes(b"test")
    monkeypatch.setattr(server_module, "__file__", str(host_file))
    monkeypatch.delenv("NODE_AGENT_EXE", raising=False)

    assert _local_agent_executable() == str(agent_file)


def test_local_agent_uses_the_same_machine_scoped_config_path_as_agent(
        monkeypatch):
    monkeypatch.setenv("PROGRAMDATA", r"D:\\SharedData")
    monkeypatch.delenv("THERMAL_AGENT_CONFIG_DIR", raising=False)
    assert _local_agent_config_path() == (
        r"D:\\SharedData\ThermalOrchestrator\agent\config.json")

    monkeypatch.setenv("THERMAL_AGENT_CONFIG_DIR", r"E:\\isolated-agent")
    assert _local_agent_config_path() == r"E:\\isolated-agent\config.json"


def test_server_restart_restores_host_agent_from_protected_config(
        tmp_path, monkeypatch):
    state = _state(tmp_path)
    state.room.set_worker_password("worker-password-123")
    state.room.set_admin_password("admin-password-123")
    config_path = tmp_path / "agent" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text("protected", encoding="utf-8")
    launched = []
    state.local_agent_launcher = lambda _state, node: launched.append(node)
    monkeypatch.setattr(server_module, "_local_agent_config_path",
                        lambda: str(config_path))
    monkeypatch.setattr(server_module, "_local_agent_process_running",
                        lambda: False)

    _restore_local_agent(state)

    assert len(launched) == 1
    assert launched[0].startswith("Host-")
    assert state.local_agent["state"] == "awaiting_uac"


def test_server_restart_keeps_existing_host_agent_instead_of_duplicate(
        tmp_path, monkeypatch):
    state = _state(tmp_path)
    state.room.set_worker_password("worker-password-123")
    state.room.set_admin_password("admin-password-123")
    config_path = tmp_path / "agent" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text("protected", encoding="utf-8")
    state.local_agent_launcher = lambda *_args: (_ for _ in ()).throw(
        AssertionError("must not start a duplicate agent"))
    monkeypatch.setattr(server_module, "_local_agent_config_path",
                        lambda: str(config_path))
    monkeypatch.setattr(server_module, "_local_agent_process_running",
                        lambda: True)

    _restore_local_agent(state)

    assert state.local_agent["state"] == "joining"


def test_retry_local_agent_does_not_start_second_nodeagent(tmp_path,
                                                           monkeypatch):
    state = _state(tmp_path)
    state.room.set_worker_password("worker-password-123")
    state.room.set_admin_password("admin-password-123")
    monkeypatch.delenv("POC_NO_BACKGROUND", raising=False)
    monkeypatch.setattr(server_module, "_local_agent_process_running",
                        lambda: True)

    status = server_module._launch_local_agent(state)

    assert status["state"] == "joining"
    assert "đã chạy" in status["message"]


def test_worker_setup_invite_is_separate_from_the_admin_join_link(
        tmp_path, monkeypatch):
    state = _state(tmp_path)
    state.room.set_worker_password("worker-password-123")
    monkeypatch.setattr(server_module, "detect_lan_url",
                        lambda: "http://10.0.0.4:8000")

    links = _invite_urls(state)

    assert links["invite_lan"] == "http://10.0.0.4:8000/join?code=THERMAL-LOCAL"
    assert links["worker_setup_lan"] == (
        "http://10.0.0.4:8000/worker-setup?code=THERMAL-LOCAL")


def test_worker_setup_page_does_not_authenticate_as_admin(tmp_path):
    state = _state(tmp_path)
    state.room.set_worker_password("worker-password-123")
    state.room.set_admin_password("admin-password-123")
    client = TestClient(create_app(state))

    response = client.get("/worker-setup?code=THERMAL-LOCAL")

    assert response.status_code == 200
    assert "NodeAgent.exe --setup" in response.text
    assert "không đăng nhập quản trị" in response.text


def test_bootstrapper_accepts_documented_dash_commands_and_starts_host():
    source = (Path(__file__).parents[2] / "installer" / "Bootstrapper"
              / "Program.cs").read_text(encoding="utf-8")
    assert "TrimStart('-')" in source
    assert '"install" or "repair" or "update" or "uninstall"' in source
    assert "StartHost(destination)" in source
    assert 'command is "repair" or "update"' in source
    # Cùng nhãn version nhưng payload khác nhau phải được cài đè. Nếu chỉ so
    # tên thư mục, install sẽ khởi động lại đúng bản cũ mà không báo gì.
    assert "SHA256.HashData(payload)" in source
    assert "ReadInstalledHash(Path.Combine(destination, PayloadHashFile))" in source
    assert '".previous-"' in source
    assert "Directory.Move(destination, previousDestination)" in source
    assert "Directory.Move(previousDestination, destination)" in source
    assert "StopRunningPayloadProcesses(versionsRoot)" in source
    assert 'new[] { "python", "NodeAgent" }' in source
    assert "process.Kill(entireProcessTree: true)" in source
    assert "Path.GetFullPath(path).StartsWith(root" in source
    assert 'Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe"' in source
    assert 'startInfo.ArgumentList.Add("/c")' in source
    assert "UseShellExecute = false" in source


def test_landing_uses_light_semantic_tokens_and_keeps_controls_usable():
    source = (Path(__file__).parents[2] / "server" / "static"
              / "dashboard.html").read_text(encoding="utf-8")

    assert "color-scheme: light" in source
    assert 'id="themeToggle"' in source
    assert "data-theme" in source
    assert "--bg" in source
    assert "--surface" in source
    assert "--ink" in source
    assert "min-height:44px; white-space:nowrap" in source
    assert "button:focus-visible" in source


def test_dashboard_prioritizes_operational_health_chart_and_adaptive_layout():
    source = (Path(__file__).parents[2] / "server" / "static"
              / "dashboard.html").read_text(encoding="utf-8")

    assert 'id="nodeKpis"' in source
    assert 'id="telemetryChart"' in source
    assert 'id="chartEmptyState"' in source
    assert 'id="chartSummary"' in source
    assert 'id="chartReadout"' in source
    assert "@media (max-width:" in source
    assert "prefers-reduced-motion" in source


def test_bootstrap_rejects_eleven_unicode_password_characters(tmp_path):
    client = TestClient(create_app(_state(tmp_path)))

    response = client.post("/api/room/bootstrap", json={
        "worker_password": "à" * 11,
        "admin_password": "admin-pass-12",
    })

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_instance_lock_releases_the_runtime_lock_file(tmp_path):
    from runtime_lock import HostInstanceLock

    lock_path = tmp_path / "host.lock"
    lock = HostInstanceLock(str(lock_path))

    lock.acquire()

    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_local_agent_retry_uses_the_one_time_worker_password(tmp_path,
                                                             monkeypatch):
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    created = client.post("/api/room/bootstrap", json={
        "worker_password": "worker-pass-12",
        "admin_password": "admin-pass-12",
        "host_contributes": False,
    })
    assert created.status_code == 200
    admin = client.post("/join", json={
        "room_code": created.json()["room"]["code"],
        "password": "admin-pass-12", "role": "admin",
    }).json()["token"]
    captured = {}

    class RunResult:
        returncode = 0

    monkeypatch.setenv("POC_NO_BACKGROUND", "0")
    monkeypatch.setattr(server_module, "_local_agent_executable",
                        lambda: str(tmp_path / "NodeAgent.exe"))
    monkeypatch.setattr(server_module.subprocess, "run",
                        lambda *args, **kwargs: (
                            captured.update(kwargs) or RunResult()))
    monkeypatch.setattr(server_module.subprocess, "Popen",
                        lambda *args, **kwargs: object())

    response = client.post(
        "/api/local-agent/start", headers={"Authorization": f"Bearer {admin}"},
        json={"worker_password": "worker-pass-12"},
    )

    assert response.status_code == 200, response.text
    assert "worker-pass-12" in captured["input"]
