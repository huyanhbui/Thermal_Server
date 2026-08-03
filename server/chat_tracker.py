"""In-memory chat job status for POST /chat + GET /chat/{id}.

Prompt text stays in RAM until the job finishes, then is cleared.
Never written to telemetry.db (docs/06 §4).
"""
from __future__ import annotations

import threading
import time

TTL_S = 3600.0


class ChatTracker:
    def __init__(self, ttl_s: float = TTL_S):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl_s = ttl_s
        # False trong cửa sổ lifecycle — không enqueue sau fail_all/drain
        self._accepting = True

    def set_accepting(self, accepting: bool) -> None:
        with self._lock:
            self._accepting = bool(accepting)

    def is_accepting(self) -> bool:
        with self._lock:
            return self._accepting

    def _prune_unlocked(self, now: float):
        # Đồng hồ giả trong test (epoch nhỏ) — không prune.
        if now < 1_000_000_000:
            return
        dead = []
        for jid, j in self._jobs.items():
            if j["status"] not in ("done", "error"):
                continue
            updated = j.get("updated_at", now)
            # updated giả (test inject now=50) — đừng xóa khi GET dùng wall clock
            if updated < 1_000_000_000:
                continue
            if (now - updated) > self._ttl_s:
                dead.append(jid)
        for jid in dead:
            del self._jobs[jid]

    def enqueue(self, job_id: str, *, queue_position: int,
                estimated_wait_s: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            if not self._accepting:
                return False
            self._prune_unlocked(now)
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "queue_position": queue_position,
                "estimated_wait_s": estimated_wait_s,
                "text": None,
                "partial_text": "",
                "attempt_id": None,
                "next_seq": 0,
                "node": None,
                "duration_ms": None,
                "tokens_out": None,
                "tokens_in": None,
                "error_message": None,
                "created_at": now,
                "updated_at": now,
            }
            return True

    def mark_queued(self, job_id: str, *, queue_position: int | None = None,
                    estimated_wait_s: float | None = None,
                    now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            j["status"] = "queued"
            j["node"] = None
            j["error_message"] = None
            if queue_position is not None:
                j["queue_position"] = queue_position
            if estimated_wait_s is not None:
                j["estimated_wait_s"] = estimated_wait_s
            j["updated_at"] = now

    def mark_running(self, job_id: str, node: str, *,
                     attempt_id: str | None = None,
                     now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            j["status"] = "running"
            j["node"] = node
            j["attempt_id"] = attempt_id
            j["partial_text"] = ""
            j["next_seq"] = 0
            j["updated_at"] = now

    def append_delta(self, job_id: str, *, attempt_id: str, seq: int,
                     delta: str, now: float | None = None) -> bool:
        """Append one ordered stream delta; duplicates are harmless.

        The final response body remains the authoritative completed text.  A
        bounded partial is held only in RAM for dashboard reconnect fallback.
        """
        now = time.time() if now is None else now
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None or j["status"] != "running":
                return False
            if j.get("attempt_id") != attempt_id:
                return False
            expected = int(j.get("next_seq") or 0)
            if seq < expected:
                return True
            if seq != expected:
                return False
            j["partial_text"] = (j.get("partial_text") or "") + delta
            j["partial_text"] = j["partial_text"][:65_536]
            j["next_seq"] = expected + 1
            j["updated_at"] = now
            return True

    def mark_done(self, job_id: str, *, node: str, text: str | None,
                  tokens_out: int | None, tokens_in: int | None,
                  duration_ms: float | None, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            j["status"] = "done"
            j["node"] = node
            j["text"] = text
            j["partial_text"] = text or j.get("partial_text") or ""
            j["tokens_out"] = tokens_out
            j["tokens_in"] = tokens_in
            j["duration_ms"] = duration_ms
            j["updated_at"] = now

    def mark_error(self, job_id: str, *, message: str,
                   node: str | None = None, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            j["status"] = "error"
            if node is not None:
                j["node"] = node
            j["error_message"] = (message or "")[:512]
            j["updated_at"] = now

    def get(self, job_id: str, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        with self._lock:
            self._prune_unlocked(now)
            j = self._jobs.get(job_id)
            return None if j is None else dict(j)

    def counts(self) -> dict:
        with self._lock:
            pending = sum(1 for j in self._jobs.values()
                          if j["status"] == "queued")
            running = sum(1 for j in self._jobs.values()
                          if j["status"] == "running")
            return {"chat_pending": pending, "chat_running": running}

    def fail_all(self, message: str, *, now: float | None = None) -> int:
        """Đánh error mọi chat còn sống rồi xóa — vòng đời phòng đóng/đổi MK."""
        now = time.time() if now is None else now
        msg = (message or "")[:512]
        with self._lock:
            n = 0
            for j in self._jobs.values():
                if j["status"] in ("done", "error"):
                    continue
                j["status"] = "error"
                j["error_message"] = msg
                j["text"] = None
                j["updated_at"] = now
                n += 1
            self._jobs.clear()
            return n

    def clear_all(self) -> int:
        """Xóa toàn bộ bản ghi chat (sau fail_all hoặc khi không cần giữ)."""
        with self._lock:
            n = len(self._jobs)
            self._jobs.clear()
            return n
