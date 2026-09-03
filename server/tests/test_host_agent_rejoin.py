"""Host agent lấy được credential mới khi phòng được tạo lại.

Kịch bản thật: NodeAgent đang chạy, người dùng mở lại và tạo phòng mới với
host_contributes=true. Agent giữ mã phòng + mật khẩu cũ trong RAM nên nó 401
liên tục; nếu Host không ghi lại config thì nó không bao giờ vào được phòng,
và nếu Host không xóa hình phạt join cũ thì nó bị 429 ngay khi có mật khẩu đúng.
"""
from __future__ import annotations

import json
import os

os.environ["POC_NO_BACKGROUND"] = "1"

import pytest
from fastapi.testclient import TestClient

import room as room_module
import server as server_module
from errors import ApiError
from room import JOIN_FAIL_BACKOFF_AFTER, Room
from server import create_app, make_state

WORKER_OLD = "worker-pass-old12"
ADMIN_OLD = "admin-pass-old12"
WORKER_NEW = "worker-pass-new99"
ADMIN_NEW = "admin-pass-new99"


def _state(tmp_path):
    return make_state(
        db_path=":memory:", model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_meta_path=str(tmp_path / "room.json"),
        bootstrap_open=True,
    )


def _cheap_hashing(monkeypatch):
    """Số vòng PBKDF2 là tham số chi phí, không phải hành vi đang kiểm.

    Hạ nó xuống để một ca kiểm nhiều lần join vẫn chạy trong tích tắc; cả
    set_* và verify_* dùng chung hằng số này nên logic xác thực không đổi.
    """
    monkeypatch.setattr(room_module, "PBKDF2_ITERATIONS", 1_000)


class _RunResult:
    """Kết quả subprocess.run tối thiểu mà _launch_local_agent thực sự đọc."""

    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _record_provisioning(monkeypatch, tmp_path, *, agent_running: bool,
                         processes=None, kill_returncode: int = 0):
    """Bắt mọi lần gọi tiến trình con của _launch_local_agent."""
    calls: list[tuple[list[str], str | None]] = []
    started: list[list[str]] = []

    def fake_run(args, **kwargs):
        argv = [str(a) for a in args]
        calls.append((argv, kwargs.get("input")))
        if "taskkill" in argv[0].lower():
            return _RunResult(kill_returncode)
        return _RunResult()

    monkeypatch.setenv("POC_NO_BACKGROUND", "0")
    monkeypatch.setattr(server_module, "_local_agent_process_running",
                        lambda: agent_running)
    monkeypatch.setattr(server_module, "_local_agent_executable",
                        lambda: str(tmp_path / "NodeAgent.exe"))
    monkeypatch.setattr(server_module, "_local_agent_config_path",
                        lambda: str(tmp_path / "agent" / "config.json"))
    monkeypatch.setattr(server_module.subprocess, "run", fake_run)
    monkeypatch.setattr(server_module.subprocess, "Popen",
                        lambda args, **kwargs: started.append(
                            [str(a) for a in args]) or object())
    if processes is not None:
        monkeypatch.setattr(server_module, "_local_agent_processes",
                            lambda: list(processes))
    return calls, started


def _provisioning_only(calls):
    return [(args, payload) for args, payload in calls
            if "--protect-config" in args]


def _killed_pids(calls) -> list[str]:
    return [argv[argv.index("/PID") + 1] for argv, _ in calls
            if "taskkill" in argv[0].lower() and "/PID" in argv]


def _admin_token(client, code: str, password: str) -> dict:
    joined = client.post("/join", json={
        "room_code": code, "password": password, "role": "admin",
    })
    assert joined.status_code in (200, 201), joined.text
    return {"Authorization": f"Bearer {joined.json()['token']}"}


def test_recreating_a_room_rewrites_the_config_of_the_running_host_agent(
        tmp_path, monkeypatch):
    """Agent đang chạy vẫn nhận mã phòng + mật khẩu mới qua config đã mã hóa."""
    _cheap_hashing(monkeypatch)
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    calls, started = _record_provisioning(monkeypatch, tmp_path,
                                          agent_running=True)

    response = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_NEW,
        "admin_password": ADMIN_NEW, "host_contributes": True,
        "regenerate_code": True,
    })

    assert response.status_code == 200, response.text
    room = response.json()["room"]
    provisioning = _provisioning_only(calls)
    assert len(provisioning) == 1, calls
    args, payload = provisioning[0]
    assert args[1:] == ["--protect-config",
                        str(tmp_path / "agent" / "config.json")]
    written = json.loads(payload)
    assert written["roomCode"] == room["code"]
    assert written["password"] == WORKER_NEW
    assert room["local_agent"]["state"] == "joining"


def test_recreating_a_room_neither_kills_nor_duplicates_the_host_agent(
        tmp_path, monkeypatch):
    """Đường tự động không dừng tiến trình nào và không xin UAC lần hai."""
    _cheap_hashing(monkeypatch)
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    calls, started = _record_provisioning(monkeypatch, tmp_path,
                                          agent_running=True)

    def _must_not_enumerate():
        raise AssertionError("bootstrap must not look for processes to stop")

    monkeypatch.setattr(server_module, "_local_agent_processes",
                        _must_not_enumerate)

    response = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_NEW,
        "admin_password": ADMIN_NEW, "host_contributes": True,
    })

    assert response.status_code == 200, response.text
    assert started == []
    commands = " ".join(" ".join(args) for args, _ in calls).lower()
    assert "taskkill" not in commands
    assert "stop-process" not in commands


def test_first_room_creation_still_asks_for_elevation_once(tmp_path,
                                                           monkeypatch):
    """Chưa có agent nào chạy thì Host ghi config rồi xin UAC đúng một lần."""
    _cheap_hashing(monkeypatch)
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    calls, started = _record_provisioning(monkeypatch, tmp_path,
                                          agent_running=False)

    response = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_NEW,
        "admin_password": ADMIN_NEW, "host_contributes": True,
    })

    assert response.status_code == 200, response.text
    assert len(_provisioning_only(calls)) == 1
    assert len(started) == 1
    assert "Start-Process" in " ".join(started[0])
    assert WORKER_NEW not in " ".join(started[0])
    assert response.json()["room"]["local_agent"]["state"] == "awaiting_uac"


def _retry_state(tmp_path, monkeypatch):
    """Phòng đã tạo (host không đóng góp) + token admin để gọi retry."""
    _cheap_hashing(monkeypatch)
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    created = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_NEW,
        "admin_password": ADMIN_NEW, "host_contributes": False,
    })
    assert created.status_code == 200, created.text
    headers = _admin_token(client, created.json()["room"]["code"], ADMIN_NEW)
    return client, headers


def test_operator_retry_stops_only_the_agent_from_this_install(tmp_path,
                                                               monkeypatch):
    """Chỉ giết PID có image path đúng payload; agent phòng khác được để yên."""
    client, headers = _retry_state(tmp_path, monkeypatch)
    packaged = str(tmp_path / "NodeAgent.exe")
    calls, started = _record_provisioning(
        monkeypatch, tmp_path, agent_running=True,
        processes=[(111, packaged),
                   (222, r"D:\OtherRoom\agent\NodeAgent.exe"),
                   (333, None)])

    response = client.post("/api/local-agent/start", headers=headers,
                           json={"worker_password": WORKER_NEW})

    assert response.status_code == 200, response.text
    assert _killed_pids(calls) == ["111"]
    # Credential mới vẫn được ghi trước khi thay tiến trình.
    assert len(_provisioning_only(calls)) == 1
    # Đã dừng được agent cũ → khởi chạy lại đúng một lần.
    assert len(started) == 1
    assert response.json()["local_agent"]["state"] == "awaiting_uac"


def test_agent_without_a_readable_path_is_never_killed_by_image_name(
        tmp_path, monkeypatch):
    """Không quy được về payload thì không giết — có thể là worker phòng khác."""
    client, headers = _retry_state(tmp_path, monkeypatch)
    calls, started = _record_provisioning(
        monkeypatch, tmp_path, agent_running=True, processes=[(444, None)])

    response = client.post("/api/local-agent/start", headers=headers,
                           json={"worker_password": WORKER_NEW})

    assert response.status_code == 200, response.text
    assert _killed_pids(calls) == []
    commands = " ".join(" ".join(argv) for argv, _ in calls).lower()
    assert "/im" not in commands
    # Không dừng được thì cũng không tạo NodeAgent thứ hai; config đã đổi nên
    # agent đang chạy vẫn tự vào lại phòng mới.
    assert started == []
    assert response.json()["local_agent"]["state"] == "joining"


def test_a_refused_kill_keeps_the_running_agent_and_the_new_config(tmp_path,
                                                                   monkeypatch):
    """Host không có quyền dừng agent elevated → vẫn còn worker, không nhân đôi."""
    client, headers = _retry_state(tmp_path, monkeypatch)
    packaged = str(tmp_path / "NodeAgent.exe")
    calls, started = _record_provisioning(
        monkeypatch, tmp_path, agent_running=True,
        processes=[(555, packaged)], kill_returncode=1)

    response = client.post("/api/local-agent/start", headers=headers,
                           json={"worker_password": WORKER_NEW})

    assert response.status_code == 200, response.text
    assert _killed_pids(calls) == ["555"]
    assert len(_provisioning_only(calls)) == 1
    assert started == []
    assert response.json()["local_agent"]["state"] == "joining"


def _fail_worker_join(room: Room, *, code: str, password: str, now: float,
                      ip: str = "10.0.0.7") -> ApiError:
    with pytest.raises(ApiError) as caught:
        room.join(room_code=code, password=password, node_name="Host-A",
                  role="worker", ip=ip, now=now)
    return caught.value


def _room_with_old_credentials(monkeypatch) -> Room:
    _cheap_hashing(monkeypatch)
    room = Room(room_code="THERMAL-AAAA")
    room.set_worker_password(WORKER_OLD)
    room.set_admin_password(ADMIN_OLD)
    return room


def _drive_into_backoff(room: Room, now: float) -> float:
    """Sai đủ số lần để backoff chặn cả lần thử đúng kế tiếp.

    Trả về mốc thời gian mà client vẫn còn bị phạt — mọi ca kiểm dùng đúng mốc
    đó, nên hành vi được kiểm là "xóa hình phạt", không phải "chờ hết hạn".
    """
    for i in range(JOIN_FAIL_BACKOFF_AFTER):
        assert _fail_worker_join(
            room, code=room.room_code, password="totally-wrong-1",
            now=now + i).status == 401
    blocked_at = now + JOIN_FAIL_BACKOFF_AFTER
    blocked = _fail_worker_join(
        room, code=room.room_code, password=WORKER_OLD, now=blocked_at)
    assert blocked.code == "RATE_LIMITED", blocked.code
    return blocked_at


def test_rotating_room_passwords_forgets_the_backoff_of_the_old_secret(
        monkeypatch):
    """Đổi mật khẩu → worker dùng mật khẩu mới vào ngay, không chờ hết backoff."""
    room = _room_with_old_credentials(monkeypatch)
    blocked_at = _drive_into_backoff(room, 1_000.0)

    room.lifecycle_rotate_passwords(WORKER_NEW, ADMIN_NEW, now=blocked_at)

    token, expires = room.join(
        room_code=room.room_code, password=WORKER_NEW, node_name="Host-A",
        role="worker", ip="10.0.0.7", now=blocked_at)
    assert token
    assert expires > blocked_at


def test_closing_the_room_forgets_the_backoff_of_the_old_secret(monkeypatch):
    """Đóng phòng cũng xóa hình phạt: mật khẩu bị hủy nên hình phạt vô nghĩa."""
    room = _room_with_old_credentials(monkeypatch)
    blocked_at = _drive_into_backoff(room, 2_000.0)

    room.lifecycle_close(now=blocked_at)
    room.set_worker_password(WORKER_NEW)
    room.set_admin_password(ADMIN_NEW)

    token, _ = room.join(
        room_code=room.room_code, password=WORKER_NEW, node_name="Host-A",
        role="worker", ip="10.0.0.7", now=blocked_at)
    assert token


def test_guessing_after_a_rotation_is_rate_limited_again_from_zero(monkeypatch):
    """Xóa hình phạt không nới rate-limit: kẻ dò mật khẩu mới bị chặn lại."""
    room = _room_with_old_credentials(monkeypatch)
    blocked_at = _drive_into_backoff(room, 3_000.0)
    room.lifecycle_rotate_passwords(WORKER_NEW, ADMIN_NEW, now=blocked_at)

    codes = []
    for i in range(JOIN_FAIL_BACKOFF_AFTER + 1):
        codes.append(_fail_worker_join(
            room, code=room.room_code, password="still-guessing-1",
            now=blocked_at + i).code)

    assert codes.count("AUTH_FAILED") == JOIN_FAIL_BACKOFF_AFTER, codes
    assert codes[-1] == "RATE_LIMITED", codes


def test_worker_joins_immediately_after_reopen_and_recreate(tmp_path,
                                                            monkeypatch):
    """Hồi quy đầu-cuối: 401 của agent cũ không được chặn phòng mới."""
    _cheap_hashing(monkeypatch)
    state = _state(tmp_path)
    client = TestClient(create_app(state))
    first = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_OLD,
        "admin_password": ADMIN_OLD,
    })
    assert first.status_code == 200, first.text
    old_code = first.json()["room"]["code"]

    assert client.post("/api/room/reopen-bootstrap").status_code == 200
    # Agent đang chạy vẫn phát lại credential cũ cho tới khi đọc lại config.
    for _ in range(JOIN_FAIL_BACKOFF_AFTER + 3):
        replay = client.post("/join", json={
            "room_code": old_code, "password": WORKER_OLD,
            "node_name": "Host-A", "role": "worker",
        })
        assert replay.status_code in (401, 429), replay.text

    recreated = client.post("/api/room/bootstrap", json={
        "display_name": "Host", "worker_password": WORKER_NEW,
        "admin_password": ADMIN_NEW, "regenerate_code": True,
    })
    assert recreated.status_code == 200, recreated.text
    new_code = recreated.json()["room"]["code"]

    joined = client.post("/join", json={
        "room_code": new_code, "password": WORKER_NEW,
        "node_name": "Host-A", "role": "worker",
    })
    assert joined.status_code in (200, 201), joined.text
