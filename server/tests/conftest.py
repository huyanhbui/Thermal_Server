"""Gán marker theo nhóm ca kiểm thử trong tài liệu G7.

Không sửa từng test cũ: tên module đã thể hiện ranh giới của
nhóm security/chaos, nên marker được gán tại lúc thu thập.
"""

from __future__ import annotations

from pathlib import Path

import pytest


SECURITY_MODULES = {
    "test_agent_privacy_s13.py",
    "test_final_input_hardening.py",
    "test_findings_fixes.py",
    "test_ingest_finite.py",
    "test_security.py",
    "test_security_g2.py",
}

CHAOS_MODULES = {
    "test_chaos_scheduler.py",
    "test_chat_lifecycle_race.py",
    "test_claim_result_lifecycle.py",
    "test_lifecycle_session.py",
    "test_lifecycle_writer_serialize.py",
    "test_room_job_isolation.py",
    "test_room_mutator_lifecycle.py",
    "test_stale_logging_lifecycle.py",
    "test_tunnel_drain.py",
    "test_tunnel_g6.py",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Gán marker để `pytest -m security/chaos` chạy đúng nhóm."""

    del config
    for item in items:
        module = Path(str(item.fspath)).name
        if module in SECURITY_MODULES:
            item.add_marker(pytest.mark.security)
        if module in CHAOS_MODULES:
            item.add_marker(pytest.mark.chaos)
