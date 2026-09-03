"""Giới hạn tần suất theo token (docs/06).

Key = token_hash. Trả retry_after_s khi vượt.
Prune key hết hạn để tránh memory tăng vô hạn.
"""
from __future__ import annotations

import threading
import time

from errors import ApiError


class TokenRateLimiter:
    """Cửa sổ trượt đơn giản theo (bucket, token_hash)."""

    def __init__(self):
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, token_hash: str, *,
              max_hits: int, window_s: float,
              now: float | None = None) -> None:
        now = time.time() if now is None else now
        key = (bucket, token_hash)
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < window_s]
            if len(hits) >= max_hits:
                oldest = hits[0]
                retry = max(0.1, window_s - (now - oldest))
                self._hits[key] = hits
                raise ApiError(
                    429, "RATE_LIMITED",
                    "Quá nhiều yêu cầu. Thử lại sau.",
                    retry_after_s=retry)
            hits.append(now)
            self._hits[key] = hits
            # Prune bucket hết hạn mỗi lần check (O(n) nhỏ)
            self._prune_expired(now, keep_key=key)

    def _prune_expired(self, now: float, *, keep_key=None) -> None:
        """Xóa bucket không còn hit trong cửa sổ (và key rỗng)."""
        dead = []
        for k, ts in self._hits.items():
            if k == keep_key:
                continue
            if not ts:
                dead.append(k)
                continue
            # Hết hạn nếu hit mới nhất đã ngoài mọi cửa sổ thực tế (≤60s)
            if now - ts[-1] >= 120.0:
                dead.append(k)
        for k in dead:
            del self._hits[k]

    def bucket_count(self) -> int:
        with self._lock:
            return len(self._hits)


# docs/06
INGEST_MAX = 2
INGEST_WINDOW_S = 1.0
CHAT_MAX = 60
CHAT_WINDOW_S = 60.0
DEFAULT_MAX = 60
DEFAULT_WINDOW_S = 60.0
JOBS_MAX = 30
JOBS_WINDOW_S = 60.0
# Streaming chat deltas — separate from DEFAULT so a 256-token
# response cannot exhaust the shared 60/min admin/worker quota.
JOB_EVENTS_MAX = 600
JOB_EVENTS_WINDOW_S = 60.0
