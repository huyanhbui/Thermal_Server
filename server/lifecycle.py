"""Cổng vòng đời phòng — read-lock mutation + write-lock purge.

Mutation (claim/result/chat/room mutators) giữ read-lock qua revalidate →
side-effect. Writer serialize FIFO: writer B chờ A kết thúc; chỉ owner reset.
Không giữ lock qua LLM/network.

Không dùng 409 ROOM_LIFECYCLE — lỗi hiện có: 401 TOKEN_REVOKED.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

from errors import ApiError

log = logging.getLogger("lifecycle")


class LifecycleWaitTimeout(Exception):
    """Hết hạn chờ vào mutation_section (không phải token revoke)."""


class LifecycleGate:
    """RW-gate: mutation = reader; close/rotate/reopen = writer (FIFO)."""

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writer_waiting = False
        self._pending_writers = 0
        self._blocking = False
        self._idle = threading.Event()
        self._idle.set()
        self._runner_ident: int | None = None
        # Test seams
        self._after_drain_hook = None
        self._after_complete_hook = None
        self._before_claim_hook = None
        self._before_result_commit_hook = None
        self._before_host_claim_hook = None
        self._before_room_mut_hook = None

    def is_blocking(self) -> bool:
        with self._cond:
            return self._blocking

    def writer_waiting(self) -> bool:
        with self._cond:
            return self._writer_waiting

    def wait_open(self, timeout: float | None = 60.0) -> bool:
        """Chờ lifecycle xong. False nếu gọi từ chính runner."""
        if threading.get_ident() == self._runner_ident:
            return False
        return self._idle.wait(timeout=timeout)

    def require_alive(self, room, auth, *, now: float) -> None:
        """Revalidate token — gọi khi đã ở trong mutation_section."""
        with self._cond:
            if self._blocking or self._writer_waiting:
                raise ApiError(
                    401, "TOKEN_REVOKED",
                    "Token đã thu hồi hoặc phòng đã đổi.")
        if not room.token_alive(
                auth.token_hash, auth.generation, now=now):
            raise ApiError(
                401, "TOKEN_REVOKED",
                "Token đã thu hồi hoặc phòng đã đổi.")

    def ensure_commit_allowed(self) -> None:
        """Sau complete: nếu writer đang chờ → abort ESG/chat (401)."""
        with self._cond:
            if self._writer_waiting or self._blocking:
                raise ApiError(
                    401, "TOKEN_REVOKED",
                    "Token đã thu hồi hoặc phòng đã đổi.")

    @contextmanager
    def commit_section(self):
        """Serialize đoạn commit chat/ESG với admission của lifecycle writer.

        ``mutation_section`` giữ reader-lock nhưng writer vẫn có thể đánh dấu
        ``_writer_waiting`` giữa một lần kiểm tra và các side-effect kế tiếp.
        Giữ condition lock trong đoạn ngắn này tạo điểm tuyến tính rõ ràng:
        hoặc result commit hoàn tất trước lifecycle, hoặc writer đã chờ và
        result bị từ chối. Không gọi network/LLM trong section này.
        """
        with self._cond:
            if self._writer_waiting or self._blocking:
                raise ApiError(
                    401, "TOKEN_REVOKED",
                    "Token đã thu hồi hoặc phòng đã đổi.")
            yield

    def require_open_and_alive(self, room, auth, *, now: float) -> None:
        """Chờ mở rồi revalidate (không giữ read-lock)."""
        self.wait_open()
        with self._cond:
            if self._blocking or self._writer_waiting:
                raise ApiError(
                    401, "TOKEN_REVOKED",
                    "Token đã thu hồi hoặc phòng đã đổi.")
        if not room.token_alive(
                auth.token_hash, auth.generation, now=now):
            raise ApiError(
                401, "TOKEN_REVOKED",
                "Token đã thu hồi hoặc phòng đã đổi.")

    def _run_before_room_mut_hook(self) -> None:
        hook = self._before_room_mut_hook
        if hook is not None:
            self._before_room_mut_hook = None
            hook()

    @contextmanager
    def mutation_section(self, timeout: float | None = 60.0):
        """Read-lock: chờ writer xong. timeout=None → chờ vô hạn.

        Hết hạn → LifecycleWaitTimeout (không 401) để /jobs/next trả 204.
        Dùng time.monotonic cho đồng hồ timeout.
        """
        if threading.get_ident() == self._runner_ident:
            yield
            return
        use_deadline = timeout is not None
        deadline = (
            time.monotonic() + max(0.0, float(timeout))
            if use_deadline else None)
        with self._cond:
            while self._writer or self._blocking or self._writer_waiting:
                if use_deadline:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LifecycleWaitTimeout()
                    self._cond.wait(timeout=min(1.0, remaining))
                else:
                    self._cond.wait(timeout=1.0)
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    def run(self, *, purge_fn, finish_fn, set_accepting) -> None:
        """Write-lock FIFO: chờ writer trước xong → purge → finish → owner reset."""
        me = threading.get_ident()
        with self._cond:
            self._pending_writers += 1
            self._writer_waiting = True
            self._blocking = True
            self._idle.clear()
            # Serialize writers: chỉ một _writer tại một thời điểm
            while self._writer:
                self._cond.notify_all()
                self._cond.wait(timeout=1.0)
            self._writer = True
            self._runner_ident = me
            self._pending_writers -= 1
            # Chờ readers nhả trước khi purge
            while self._readers > 0:
                self._cond.notify_all()
                self._cond.wait(timeout=1.0)
            set_accepting(False)
            log.info("[ROOM] lifecycle gate ON (write)")
        try:
            purge_fn()
            hook = self._after_drain_hook
            if hook is not None:
                hook()
            finish_fn()
        finally:
            with self._cond:
                if self._runner_ident != me:
                    log.error(
                        "[ROOM] lifecycle finally không phải owner "
                        "(me=%s owner=%s) — bỏ reset",
                        me, self._runner_ident)
                    return
                self._writer = False
                self._runner_ident = None
                if self._pending_writers > 0:
                    # Writer kế tiếp: giữ gate đóng, accepting=False
                    self._writer_waiting = True
                    self._blocking = True
                    log.info("[ROOM] lifecycle handoff → writer tiếp")
                else:
                    set_accepting(True)
                    self._blocking = False
                    self._writer_waiting = False
                    self._idle.set()
                    log.info("[ROOM] lifecycle gate OFF")
                self._cond.notify_all()
