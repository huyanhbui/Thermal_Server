"""Kiểm thử hành vi dashboard, event tức thời và log xoay vòng của G7."""

from __future__ import annotations

import asyncio
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from forecast_cache import NodeForecast
from server import (
    _publish_node_event,
    _subscribe_admin_events,
    _unsubscribe_admin_events,
    build_state_payload,
    create_app,
    configure_logging,
    make_state,
)
from fastapi.testclient import TestClient


def test_server_log_uses_five_file_rotating_budget(tmp_path):
    log_path = tmp_path / "server.log"
    configure_logging(str(log_path))
    root = logging.getLogger()
    try:
        handlers = [h for h in root.handlers
                    if isinstance(h, RotatingFileHandler)]
        assert len(handlers) == 1
        assert handlers[0].baseFilename == str(log_path)
        assert handlers[0].maxBytes == 10 * 1024 * 1024
        assert handlers[0].backupCount == 4
    finally:
        configure_logging()


def test_server_log_rollover_keeps_at_most_five_files(tmp_path):
    log_path = tmp_path / "server.log"
    configure_logging(str(log_path))
    root = logging.getLogger()
    try:
        handler = next(h for h in root.handlers
                       if isinstance(h, RotatingFileHandler)
                       and h.baseFilename == str(log_path))
        handler.maxBytes = 128
        for index in range(80):
            root.info("[TEST] rollover record %03d %s", index, "x" * 32)
        handler.flush()
        files = list(tmp_path.glob("server.log*"))
        assert len(files) <= 5
        assert (tmp_path / "server.log.1").exists()
    finally:
        configure_logging()


def test_node_payload_exposes_decision_threshold_used_by_forecast(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_password="worker-pass",
        admin_password="admin-pass",
    )
    now = 1_000.0
    state.store.insert("Node-A", now, 70.0, None, 20.0, 40.0)
    state.forecast_cache.put(NodeForecast(
        node="Node-A", state="AT_RISK", current_temp_c=70.0,
        predicted_max_c=78.2, effective_threshold_c=75.0,
        last_sample_ts=now, computed_at=now,
        reason="flagged pred=78.2 >= 75.0"))

    node = build_state_payload(state, now + 1)["nodes"][0]

    assert node["decision_threshold_c"] == 75.0
    assert node["predicted_max"] == 78.2
    assert node["state"] == "AT_RISK"


def test_admin_node_event_is_bounded_and_unsubscribable(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_password="worker-pass",
        admin_password="admin-pass",
    )

    async def exercise():
        ident, queue = _subscribe_admin_events(state)
        _publish_node_event(
            state, "Node-A", "cleared", state_name="READY",
            reason="cleared pred=70.0 <= 72.0", predicted_max=70.0,
            decision_threshold_c=75.0)
        event = await asyncio.wait_for(queue.get(), timeout=0.5)
        assert event == {
            "type": "node_event",
            "node": "Node-A",
            "event": "cleared",
            "state": "READY",
            "reason": "cleared pred=70.0 <= 72.0",
            "predicted_max": 70.0,
            "decision_threshold_c": 75.0,
        }
        _unsubscribe_admin_events(state, ident)
        assert ident not in state._ws_admin_subscribers

    asyncio.run(exercise())


def test_admin_websocket_receives_node_event_before_next_snapshot(tmp_path):
    state = make_state(
        db_path=":memory:",
        model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
        room_password="worker-pass",
        admin_password="admin-pass",
    )
    client = TestClient(create_app(state))
    token = client.post("/join", json={
        "room_code": state.room.room_code,
        "password": "admin-pass",
        "role": "admin",
    }).json()["token"]

    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token})
        first = socket.receive_json()
        assert first.get("type") != "node_event"
        _publish_node_event(
            state, "Node-A", "cleared", state_name="READY",
            reason="cleared", predicted_max=70.0,
            decision_threshold_c=75.0)
        event = socket.receive_json()
        assert event["type"] == "node_event"
        assert event["event"] == "cleared"
        assert event["node"] == "Node-A"


def test_dashboard_exposes_an_accessible_light_first_operational_view():
    """Chế độ sáng là mặc định; dark mode là lựa chọn có nhớ và có nhãn."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert re.search(r"color-scheme\s*:\s*light\b", html)
    assert 'id="themeToggle"' in html
    assert 'id="themeToggleLanding"' in html
    assert "data-theme" in html
    assert re.search(r"data-theme\s*=\s*[\"']dark[\"']", html)
    assert "localStorage" in html
    assert "theme" in html
    assert "--surface" in html
    assert "--ink" in html
    assert "--line" in html


def test_dashboard_defaults_to_light_and_never_infers_dark_from_the_os():
    """Không có lựa chọn đã lưu thì phải là sáng — không đoán theo hệ điều hành."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    # Mặc định sáng phải nằm ngay trên nhánh đọc localStorage, không phải
    # một biến 'dark' được đặt ở chỗ khác.
    assert re.search(
        r"localStorage\.getItem\(THEME_KEY\)[^;]*\|\|\s*['\"]light['\"]", html)
    assert re.search(r"let theme\s*=\s*['\"]light['\"]", html)
    # Nhánh dark-first cũ (bám prefers-color-scheme) không được quay lại.
    assert "prefers-color-scheme" not in html
    assert not re.search(r"prefersLight\s*\?", html)
    assert not re.search(r"theme\s*=\s*['\"]dark['\"]\s*;", html)


def test_dashboard_keeps_the_durable_theme_key_and_migrates_the_legacy_one():
    """Đổi khóa localStorage sẽ quên lựa chọn của người dùng — phải di trú."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    assert re.search(
        r"const THEME_KEY\s*=\s*['\"]thermal_dashboard_theme['\"]", html)
    assert re.search(r"LEGACY_THEME_KEYS\s*=\s*\[[^\]]*thermal_theme", html)
    assert "function migrateLegacyTheme" in html
    assert "migrateLegacyTheme()" in html
    assert re.search(r"localStorage\.removeItem\(key\)", html)
    # Nút bật/tắt vẫn ghi vào đúng khóa đó.
    assert re.search(r"localStorage\.setItem\(THEME_KEY,\s*theme\)", html)


def test_dashboard_chart_paints_grid_labels_and_series_from_theme_tokens():
    """Đồ thị SVG phải đổi màu theo theme, không hardcode màu của chế độ sáng."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    for hardcoded in ("#d7e0eb", "#526176", "#b4232d"):
        assert hardcoded not in html
    assert "--legend:#" not in html  # chú giải cũng đi qua token
    assert re.search(
        r"\.thermal-chart \.chart-grid\s*\{[^}]*stroke:var\(--line\)", html)
    assert re.search(
        r"\.thermal-chart \.chart-axis\s*\{[^}]*fill:var\(--muted\)", html)
    assert re.search(
        r"\.thermal-chart \.chart-threshold\s*\{[^}]*stroke:var\(--danger\)",
        html)
    assert 'class="chart-grid"' in html
    assert 'class="chart-axis"' in html
    assert 'class="chart-threshold' in html
    assert "var(--chart-${index % seriesTokens + 1})" in html
    assert "--chart-1:" in html
    assert re.search(r"\[data-theme=\"dark\"\][^{]*\{[^}]*--chart-1:", html)


def test_dashboard_uses_one_token_stack_and_readable_status_text():
    """Một bảng token duy nhất; chữ trạng thái dùng --muted để đủ tương phản."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    assert len(re.findall(r":root\s*\{", html)) == 1
    assert re.search(r"#chatStatus\s*\{[^}]*color:var\(--muted\)", html)
    assert re.search(r"#copyStatus\s*\{[^}]*color:var\(--muted\)", html)


def test_dashboard_landing_tabs_stay_tappable_and_keep_their_focus_ring():
    """Tab đủ 44px và không bị tắt outline khi đang ở trạng thái active."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    assert re.search(
        r"\.landing-tabs button\s*\{[^}]*min-height:44px", html)
    active_rules = re.findall(
        r"\.landing-tabs button\.active\s*\{([^}]*)\}", html)
    assert active_rules
    for rule in active_rules:
        assert "outline" not in rule
    assert "button:focus-visible" in html


def test_dashboard_keeps_a_bounded_accessible_fifteen_minute_chart():
    """Đồ thị chỉ là bộ đệm client-side, không tạo API lịch sử mới."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    assert 'id="telemetryChart"' in html
    assert 'id="chartEmptyState"' in html
    assert 'id="chartSummary"' in html
    assert 'id="chartReadout"' in html
    assert "aria-live" in html
    assert re.search(
        r"CHART_WINDOW_MS\s*=\s*15\s*\*\s*60\s*\*\s*1000", html)
    assert "MAX_CHART_POINTS" in html
    assert "MAX_HISTORY_POINTS" in html
    assert "telemetryHistory" in html
    assert "pruneTelemetryHistory" in html
    assert "downsampleTelemetryHistory" in html
    assert re.search(
        r"telemetryHistory\.length\s*>\s*MAX_HISTORY_POINTS", html)
    assert re.search(r"telemetryHistory\.(?:shift|splice)\(", html)
    assert "/api/telemetry" not in html


def test_dashboard_keeps_semantic_status_labels_and_responsive_motion_safety():
    """Màu chỉ hỗ trợ; trạng thái vận hành, mobile và reduced motion đều rõ ràng."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")

    assert 'id="nodeKpis"' in html
    assert "AT RISK" in html
    assert "WARMING UP" in html
    assert "OFFLINE" in html
    assert "node_event" in html
    assert "decision_threshold_c" in html
    assert re.search(r"prefers-reduced-motion\s*:\s*reduce", html)
    assert "@media (max-width:" in html
    assert "animatedChatJobs" in html
    assert "statusLabel" in html
    assert "dataset.offline" in html
    assert "const seen" not in html


def test_dashboard_hides_missing_or_stale_node_values_instead_of_rendering_na():
    """Node cũ không được trưng ra số n/a hoặc lý do STALE lặp lại."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "function setNodeMetric" in html
    assert "metric.hidden = !available" in html
    assert "const live = st !== 'STALE'" in html
    assert "alerts.push(`⏸ ${n.name}: telemetry cũ" not in html
    assert "if (n.reason) return 'Lý do: ' + n.reason;" not in html


def test_dashboard_hides_esg_rows_that_have_no_measured_evidence():
    """Chưa có J/token thì empty-state; đã có mẫu sensor thì hiện số tạm."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "#esgBlock1 .row" in html
    assert "hasMeasuredValue" in html
    assert "document.getElementById('esgBlock2').hidden = false" in html
    assert "document.getElementById('esgBlock3').hidden = false" in html
    assert 'id="esgMeasuredEmpty"' in html
    assert "energy_source=sensor" in html
    assert "CPU temperature alone is not MEASURED energy" in html


def test_dashboard_centers_chat_and_raises_token_ceiling():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'class="chat-column"' in html
    assert "CHAT_MAX_TOKENS = 4096" in html
    assert "max_tokens: CHAT_MAX_TOKENS" in html
    assert "formatChatTokens" in html
    assert "compactChatHistory" in html
    assert "buildPromptWithContext" in html
    assert "chatContextTurns" in html
    assert 'id="chatContextMeta"' in html
    assert 'id="chatTokens"' in html
    assert "CHAT_PROMPT_MAX_CHARS" in html


def test_dashboard_chart_empty_state_cannot_stack_with_series():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "setTelemetryChartVisibility" in html
    assert 'data-has-telemetry="0"' in html
    assert '.chart-panel[data-has-telemetry="1"] #chartEmptyState' in html
    assert '.chart-panel[data-has-telemetry="0"] #telemetryChart' in html
    assert 'class="chart-body"' in html


def test_dashboard_exports_esg_events_and_room_audit_separately():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'id="csvEsgEventsLink"' in html
    assert "/api/esg.csv" in html
    assert "/api/esg/report.csv" in html
    assert "/api/audit.csv" in html
    assert "Export ESG events" in html
    assert "Export room audit" in html
    assert "Could not download " in html


def test_dashboard_syncs_ui_paths_for_landing_login_and_app():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "function syncUiPath" in html
    assert "syncUiPath('/app')" in html
    assert "syncUiPath('/login')" in html
    assert "syncUiPath('/landing')" in html
    assert "popstate" in html


def test_dashboard_exposes_operational_empty_state_and_accessible_password_toggles():
    """UI phải hiển thị được Host agent và cho phép kiểm tra mật khẩu đã nhập."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'id="hostEmpty"' in html
    assert 'id="retryLocalAgent"' in html
    assert "retryLocalAgent()" in html
    assert 'id="hostAgentCredentials"' in html
    assert 'aria-controls="hostAgentWorker"' in html
    assert "LOCAL_AGENT_CREDENTIALS_UNAVAILABLE" in html
    assert 'id="inviteWorker"' in html
    assert "worker_setup_lan" in html
    assert "local_agent" in html
    for input_id in (
        "createWorker", "createAdmin", "joinPass", "bootWorker", "bootAdmin",
    ):
        assert f'aria-controls="{input_id}"' in html
        assert f"togglePassword('{input_id}', this)" in html
    assert "aria-pressed" in html


def test_dashboard_has_a_truthful_public_landing_view_before_authentication():
    """Landing explains the real flow; login is not the marketing page."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'id="landingView"' in html
    assert 'id="openCreateFromLanding"' in html
    assert 'id="openJoinFromLanding"' in html
    assert "Workers only connect outward" in html
    assert "Measured stays separate from inferred" in html
    assert "model READY" in html
    assert "showAuthFromLanding" in html
    assert 'lang="en"' in html
    assert 'id="themeToggleLanding"' in html
    assert "thermal_owm_api_key" in html
    assert "inviteQrCanvas" in html


def test_dashboard_does_not_reserve_blank_map_space_and_explains_empty_activity():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert ".map { position:relative; display:flex; gap:24px; align-items:flex-start; min-height:260px; }" not in html
    assert "No dispatch decisions yet" in html


def test_dashboard_uses_text_and_svg_not_emoji_as_structural_icons():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    for emoji in ("🌡️", "💬", "🖥️", "🔴", "🟢", "🔵"):
        assert emoji not in html


def test_dashboard_consumes_real_chat_stream_and_has_http_copy_fallback():
    """Dashboard không được phụ thuộc riêng polling hay Clipboard API bảo mật."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "chat_token" in html
    assert "chat_result" in html
    assert "llm_readiness" in html
    assert "NO_LLM_READY" not in html  # backend truyền thông điệp, UI không hard-code mã.
    assert "navigator.clipboard ||" in html
    assert "document.execCommand('copy')" in html
    assert "/api/audit.csv" in html
    assert "Dựa trên " not in html


def test_dashboard_keeps_an_in_memory_chat_history_with_an_actionable_retry():
    """Lịch sử chat ở phía trình duyệt, không là nơi server lưu prompt."""
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'id="chatHistory"' in html
    assert 'id="chatRetry"' in html
    assert "appendChatHistory" in html
    assert "retryLastChat" in html


def test_dashboard_checks_backend_revision_before_using_dashboard_apis():
    html = (Path(__file__).parents[1] / "static" / "dashboard.html").read_text(
        encoding="utf-8")
    assert "DASHBOARD_API_REVISION" in html
    assert "verifyApiRevision" in html
    assert 'fetch("/api/version")' in html
    assert 'id="runtimeNotice"' in html


def test_direct_server_entrypoint_defines_run_server_before_main_guard():
    """Chạy `python server.py` phải tìm thấy run_server trước khi gọi nó."""
    source = (Path(__file__).parents[1] / "server.py").read_text(
        encoding="utf-8")
    assert source.index("def run_server") < source.index(
        'if __name__ == "__main__":')
