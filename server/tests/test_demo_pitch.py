"""Tests for scripts/demo_pitch.py — Pitching Demo CLI Automation."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root and scripts dir are on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import demo_pitch


def test_unicode_display_width_vietnamese():
    """Kiểm tra tính toán độ rộng ký tự tiếng Việt có dấu chuẩn xác."""
    assert demo_pitch.display_width("Xin chào") == 8
    assert demo_pitch.display_width("Tóm tắt lịch sử Trái Đất") == 24
    assert demo_pitch.display_width("AI") == 2

    # ANSI stripped width
    colored = f"{demo_pitch.Style.GREEN}65.2°C{demo_pitch.Style.RESET}"
    assert demo_pitch.display_width(colored) == 6


def test_padding_and_truncation():
    """Kiểm tra căn lề và cắt chuỗi."""
    padded = demo_pitch.pad_right("Chào", 10)
    assert demo_pitch.display_width(padded) == 10

    centered = demo_pitch.pad_center("Node-A", 12)
    assert demo_pitch.display_width(centered) == 12

    left_pad = demo_pitch.pad_left("50.0°C", 10)
    assert demo_pitch.display_width(left_pad) == 10

    long_text = "Đây là một chuỗi văn bản rất dài cần được cắt bớt"
    truncated = demo_pitch.truncate_text(long_text, 20)
    assert demo_pitch.display_width(truncated) <= 20
    assert truncated.endswith("...")


def test_color_temp_and_energy():
    """Kiểm tra format màu nhiệt độ và năng lượng."""
    t_cool = demo_pitch.color_temp(55.0, use_color=True)
    assert "55.0°C" in t_cool
    assert demo_pitch.Style.GREEN in t_cool

    t_warm = demo_pitch.color_temp(68.0, use_color=True)
    assert "68.0°C" in t_warm
    assert demo_pitch.Style.YELLOW in t_warm

    t_hot = demo_pitch.color_temp(78.0, use_color=True)
    assert "78.0°C" in t_hot
    assert demo_pitch.Style.RED in t_hot

    t_none = demo_pitch.color_temp(None, use_color=False)
    assert "N/A" in t_none

    e_val = demo_pitch.color_energy(145.2, use_color=False)
    assert "145.2 J" in e_val


def test_runner_auth_success():
    """Kiểm tra authenticate thành công nhận token."""
    runner = demo_pitch.DemoPitchRunner(
        host="http://test-host:8000",
        room_code="THERMAL-TEST",
        admin_pass="secret123",
        use_color=False,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "token": "mock-admin-jwt-token-12345",
        "room_config": {"model_id": "qwen2.5-0.5b"},
    }

    with patch.object(runner.session, "post", return_value=mock_resp) as mock_post:
        assert runner.authenticate() is True
        assert runner.token == "mock-admin-jwt-token-12345"
        assert runner.headers["Authorization"] == "Bearer mock-admin-jwt-token-12345"
        mock_post.assert_called_once_with(
            "http://test-host:8000/join",
            json={"room_code": "THERMAL-TEST", "password": "secret123", "role": "admin"},
            timeout=10.0,
        )


def test_runner_auth_failure():
    """Kiểm tra authenticate thất bại khi sai mật khẩu."""
    runner = demo_pitch.DemoPitchRunner(
        host="http://test-host:8000",
        room_code="THERMAL-TEST",
        admin_pass="wrong-password",
        use_color=False,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"error": {"message": "Sai mã phòng hoặc mật khẩu."}}
    mock_resp.text = "Sai mật khẩu"

    with patch.object(runner.session, "post", return_value=mock_resp):
        assert runner.authenticate() is False
        assert runner.token is None


def test_runner_run_single_job_lifecycle():
    """Kiểm tra chu trình 1 job: post chat -> polling -> done."""
    runner = demo_pitch.DemoPitchRunner(
        host="http://test-host:8000",
        room_code="THERMAL-TEST",
        admin_pass="secret123",
        poll_interval=0.01,
        timeout=5.0,
        use_color=False,
    )
    runner.token = "valid-token"
    runner.headers = {"Authorization": "Bearer valid-token"}

    # Mock POST /chat
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 202
    mock_post_resp.json.return_value = {"job_id": "job-abc-123", "queue_position": 1}

    # Mock GET /chat/job-abc-123: first running, then done
    mock_poll_running = MagicMock()
    mock_poll_running.status_code = 200
    mock_poll_running.json.return_value = {"job_id": "job-abc-123", "status": "running", "node": "Node-A"}

    mock_poll_done = MagicMock()
    mock_poll_done.status_code = 200
    mock_poll_done.json.return_value = {
        "job_id": "job-abc-123",
        "status": "done",
        "node": "Node-A",
        "duration_ms": 1200.0,
        "tokens_in": 15,
        "tokens_out": 85,
        "text": "Trái Đất hình thành cách đây khoảng 4.5 tỷ năm...",
    }

    # Mock GET /api/state
    mock_state_resp = MagicMock()
    mock_state_resp.status_code = 200
    mock_state_resp.json.return_value = {
        "nodes": [
            {"name": "Node-A", "cpu_temp": 63.5, "power_w": 35.0, "predicted_max": 65.0}
        ]
    }

    with patch.object(runner.session, "post", return_value=mock_post_resp), \
         patch.object(runner.session, "get", side_effect=[mock_poll_running, mock_poll_done, mock_state_resp]):
        res = runner.run_single_job(1, "Tóm tắt lịch sử Trái Đất")
        assert res["status"] == "done"
        assert res["node"] == "Node-A"
        assert res["tokens_out"] == 85
        assert res["duration_ms"] == 1200.0
        assert res["peak_temp_c"] == 63.5
        assert res["energy_j"] == pytest.approx(42.0, 0.1)


def test_full_runner_run_mocked(capsys):
    """Kiểm tra toàn bộ luồng chạy 5 prompt và in bảng ASCII."""
    runner = demo_pitch.DemoPitchRunner(
        host="http://test-host:8000",
        room_code="THERMAL-TEST",
        admin_pass="secret123",
        delay=0.0,
        poll_interval=0.01,
        timeout=2.0,
        use_color=False,
    )

    with patch.object(runner, "authenticate", return_value=True), \
         patch.object(runner, "run_single_job", side_effect=[
             {"index": 1, "prompt": "Prompt 1", "status": "done", "node": "Node-A", "peak_temp_c": 61.2, "energy_j": 110.5, "tokens_out": 80, "duration_ms": 1100.0},
             {"index": 2, "prompt": "Prompt 2", "status": "done", "node": "Node-B", "peak_temp_c": 58.4, "energy_j": 95.0, "tokens_out": 75, "duration_ms": 950.0},
             {"index": 3, "prompt": "Prompt 3", "status": "done", "node": "Node-A", "peak_temp_c": 64.0, "energy_j": 125.0, "tokens_out": 90, "duration_ms": 1300.0},
             {"index": 4, "prompt": "Prompt 4", "status": "done", "node": "Node-B", "peak_temp_c": 59.5, "energy_j": 105.0, "tokens_out": 82, "duration_ms": 1050.0},
             {"index": 5, "prompt": "Prompt 5", "status": "done", "node": "Node-C", "peak_temp_c": 55.0, "energy_j": 88.0, "tokens_out": 70, "duration_ms": 880.0},
         ]):
        success = runner.run()
        assert success is True
        captured = capsys.readouterr().out
        assert "THERMAL ORCHESTRATOR" in captured
        assert "Prompt 1" in captured
        assert "Node-A" in captured
        assert "61.2°C" in captured
        assert "110.5 J" in captured
        assert "TỔNG HỢP KẾT QUẢ ĐIỀU PHỐI & CHỈ SỐ ESG" in captured
        assert "5/5 hoàn thành" in captured
