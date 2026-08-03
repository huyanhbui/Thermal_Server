"""Job queue + reservation. Agents PULL jobs đã được scheduler giữ chỗ.

Scheduler CHỌN (score → target). next_job/claim chỉ TRAO job có target=node.
Bỏ _throttled (M14). FastAPI sync routes chạy threadpool — mọi mutating
method có lock.
"""
import logging
import threading
import uuid
from collections import deque

log = logging.getLogger("balancer")

# Burn: thêm grace để result muộn vài trăm ms không bị LEASE_EXPIRED.
BURN_LEASE_GRACE_S = 5.0


class LoadBalancer:
    def __init__(self, max_queue=10):
        self.max_queue = max_queue
        self._queue = deque()       # pending + reserved (target set)
        self._flags = set()
        self._dispatched = {}
        self._failed = {}          # id -> detail
        self._active = {}          # node -> job đang chạy (đã claim)
        self._lock = threading.Lock()
        # False trong cửa sổ lifecycle — chặn enqueue sau drain
        self._accepting = True

    def set_accepting(self, accepting: bool) -> None:
        with self._lock:
            self._accepting = bool(accepting)
            log.info("[BALANCER] accepting=%s", self._accepting)

    def is_accepting(self) -> bool:
        with self._lock:
            return self._accepting

    def enqueue_job(self, duration_s=10, cores=0, target=None,
                    job_type="burn", **extra):
        with self._lock:
            if not self._accepting:
                return None
            if len(self._queue) >= self.max_queue:
                return None
            job = {
                "id": uuid.uuid4().hex[:8],
                "duration_s": duration_s,
                "cores": cores,
                "target": target,
                "type": job_type,
                "reserved_until": None,
                "attempts": 0,
                "attempt_id": None,
            }
            job.update(extra)
            self._queue.append(job)
            return dict(job)

    def drop_pending(self, job_id, *, code="CANCELLED"):
        """Gỡ job pending/reserved chưa claim — rollback enqueue khi lifecycle chen."""
        with self._lock:
            for i, j in enumerate(self._queue):
                if j["id"] == job_id:
                    job = self._queue[i]
                    del self._queue[i]
                    self.clear_prompt(job)
                    self._failed[job_id] = {
                        "code": code,
                        "detail": "rollback enqueue during lifecycle",
                    }
                    return True
            return False

    def set_flag(self, node, flagged):
        with self._lock:
            before = node in self._flags
            (self._flags.add if flagged else self._flags.discard)(node)
            if flagged != before:
                log.info("[BALANCER] %s %s", node,
                         "FLAGGED - no new jobs" if flagged
                         else "cleared - jobs resume")

    def is_flagged(self, node):
        with self._lock:
            return node in self._flags

    def pending(self):
        """Job chưa giữ chỗ (target is None). Snapshot list."""
        with self._lock:
            return [dict(j) for j in self._queue if j.get("target") is None]

    def reserved(self):
        """Job đang giữ chỗ (target set, chưa claim)."""
        with self._lock:
            return [dict(j) for j in self._queue
                    if j.get("target") is not None]

    def reserve(self, job_id, node, until, now=None, *,
                scheduler_mode=None, assign_temp_c=None,
                assign_predicted_max_c=None, avoided_temp_c=None):
        with self._lock:
            if not self._accepting:
                return None
            for j in self._queue:
                if j["id"] == job_id and j.get("target") is None:
                    j["target"] = node
                    j["reserved_until"] = until
                    j["attempts"] = j.get("attempts", 0) + 1
                    j["attempt_id"] = uuid.uuid4().hex
                    if scheduler_mode is not None:
                        j["scheduler_mode"] = scheduler_mode
                    # Luôn ghi đè stamp nhiệt — None xóa stamp lần gán trước
                    # (re-reserve 1 ứng viên không được giữ ΔT cũ).
                    had_avoided = j.get("avoided_temp_c") is not None
                    j["assign_temp_c"] = assign_temp_c
                    j["assign_predicted_max_c"] = assign_predicted_max_c
                    j["avoided_temp_c"] = avoided_temp_c
                    if had_avoided and avoided_temp_c is None:
                        log.info("[BALANCER] cleared thermal stamps on "
                                 "re-reserve job %s", job_id)
                    log.info("[BALANCER] reserved job %s -> %s until %.1f "
                             "(attempt %d)",
                             job_id, node, until, j["attempts"])
                    return dict(j)
            return None

    def claim(self, node, now=None):
        """Worker lấy job đã giữ chỗ cho chính nó.

        Không kiểm reserved_until ở đây — vòng reap là nguồn sự thật hết hạn.
        (Tránh lệch đồng hồ giữa schedule(now giả) và HTTP time.time().)
        """
        import time as _time
        now = _time.time() if now is None else now
        with self._lock:
            if not self._accepting:
                return None
            for i, job in enumerate(self._queue):
                if job.get("target") != node:
                    continue
                del self._queue[i]
                self._dispatched[node] = self._dispatched.get(node, 0) + 1
                active = dict(job)
                jtype = active.get("type") or "burn"
                if jtype == "chat":
                    lease = float(active.get("deadline_s") or 60)
                else:
                    lease = (float(active.get("deadline_s")
                                   or active.get("duration_s") or 60)
                             + BURN_LEASE_GRACE_S)
                active["claimed_at"] = now
                active["active_deadline"] = now + lease
                self._active[node] = active
                log.info("[BALANCER] job %s claimed by %s (%ss, cores=%s)",
                         active["id"], node, active.get("duration_s"),
                         active.get("cores"))
                return dict(active)
            return None

    def list_active(self):
        """Snapshot (node, job) đang chạy."""
        with self._lock:
            return [(n, dict(j)) for n, j in self._active.items()]

    def next_job(self, node, node_temps=None, now=None):
        """Tương thích cũ: chỉ claim job đã reserve — không chọn theo temp."""
        return self.claim(node, now=now)

    def requeue_front(self, job_id):
        with self._lock:
            for i, j in enumerate(self._queue):
                if j["id"] == job_id:
                    job = dict(j)
                    del self._queue[i]
                    job["target"] = None
                    job["reserved_until"] = None
                    self._queue.appendleft(job)
                    log.info("[BALANCER] job %s requeued to front", job_id)
                    return dict(job)
            return None

    def release_reservations_for(self, node):
        """Chỉ trả giữ chỗ CHƯA claim về đầu hàng đợi (R6)."""
        released = []
        with self._lock:
            kept = deque()
            front = []
            for j in self._queue:
                if j.get("target") == node:
                    job = dict(j)
                    job["target"] = None
                    job["reserved_until"] = None
                    front.append(job)
                    released.append(job["id"])
                else:
                    kept.append(j)
            self._queue = deque(front + list(kept))
        for jid in released:
            log.info("[BALANCER] released reservation %s from %s", jid, node)
        return released

    def peek_active(self, node):
        with self._lock:
            j = self._active.get(node)
            return None if j is None else dict(j)

    def cancel_active(self, node, code="NODE_GONE"):
        """Hủy job đang chạy — KHÔNG requeue (tránh hai node cùng job)."""
        with self._lock:
            active = self._active.pop(node, None)
            if active is None:
                return None
            jid = active["id"]
            self._failed[jid] = {"code": code, "detail": f"cancelled on {node}"}
            log.info("[BALANCER] cancelled active job %s on %s (%s)",
                     jid, node, code)
            return dict(active)

    def requeue_active_as_pending(self, node, job_id=None):
        """Chat kick/leave: trả job active về đầu hàng đợi (giữ prompt)."""
        with self._lock:
            active = self._active.pop(node, None)
            if active is None:
                return None
            if job_id is not None and active["id"] != job_id:
                self._active[node] = active
                return None
            job = dict(active)
            job["target"] = None
            job["reserved_until"] = None
            self._failed.pop(job["id"], None)
            self._queue.appendleft(job)
            log.info("[BALANCER] job %s requeued from active on %s (chat)",
                     job["id"], node)
            return dict(job)

    def return_job_to_pending(self, job):
        """Sau complete lỗi — đẩy lại pending (giữ attempts/prompt)."""
        with self._lock:
            j = dict(job)
            j["target"] = None
            j["reserved_until"] = None
            self._failed.pop(j["id"], None)
            self._queue.appendleft(j)
            log.info("[BALANCER] job %s returned to pending for retry",
                     j["id"])
            return dict(j)

    def fail(self, job_id, code="NO_CAPACITY", detail=None):
        with self._lock:
            for i, j in enumerate(self._queue):
                if j["id"] == job_id:
                    del self._queue[i]
                    self._failed[job_id] = {"code": code, "detail": detail}
                    log.info("[BALANCER] job %s failed: %s %s",
                             job_id, code, detail)
                    return True
            return False

    def complete(self, node, job_id=None):
        with self._lock:
            active = self._active.pop(node, None)
            if active is None:
                return None
            if job_id is not None and active["id"] != job_id:
                # mismatch — put back
                self._active[node] = active
                return None
            return dict(active)

    def assign_to_host(self, job, now, *, scheduler_mode=None):
        """P2: giữ chỗ cho tiến trình suy luận trên host (__host__)."""
        with self._lock:
            for i, j in enumerate(self._queue):
                if j["id"] == job["id"]:
                    j["target"] = "__host__"
                    j["reserved_until"] = now + 60.0
                    j["attempts"] = j.get("attempts", 0) + 1
                    j["attempt_id"] = uuid.uuid4().hex
                    if scheduler_mode is not None:
                        j["scheduler_mode"] = scheduler_mode
                    # Host không có node bị né — xóa stamp worker cũ.
                    j["assign_temp_c"] = None
                    j["assign_predicted_max_c"] = None
                    j["avoided_temp_c"] = None
                    log.info("[BALANCER] job %s assigned to host (P2) "
                             "(attempt %d)",
                             j["id"], j["attempts"])
                    return dict(j)
            return None

    def get_failed(self, job_id):
        with self._lock:
            return self._failed.get(job_id)

    def queue_position(self, job_id):
        """1-based position among pending+reserved; None if missing."""
        with self._lock:
            for i, j in enumerate(self._queue):
                if j["id"] == job_id:
                    return i + 1
            return None

    def clear_prompt(self, job):
        """Xóa prompt khỏi bản ghi job sau khi xong (docs/06 §4)."""
        if job is None:
            return
        job.pop("prompt", None)

    def drain_all(self, *, code="ROOM_CLOSED"):
        """Hủy toàn bộ pending/reserved/active — không requeue (vòng đời phòng).

        Xóa prompt khỏi mọi job trước khi bỏ khỏi hàng đợi. Trả số job đã hủy.
        """
        cancelled = []
        with self._lock:
            while self._queue:
                job = self._queue.popleft()
                jid = job["id"]
                self.clear_prompt(job)
                self._failed[jid] = {
                    "code": code,
                    "detail": "room lifecycle purge",
                }
                cancelled.append(jid)
            for node in list(self._active.keys()):
                active = self._active.pop(node)
                jid = active["id"]
                self.clear_prompt(active)
                self._failed[jid] = {
                    "code": code,
                    "detail": f"cancelled on {node}",
                }
                cancelled.append(jid)
            self._flags.clear()
            # Giữ _dispatched/_failed để audit ngắn; không còn job sống.
        if cancelled:
            log.info("[BALANCER] drain_all code=%s cancelled=%d ids=%s",
                     code, len(cancelled), ",".join(cancelled[:12]))
        return cancelled

    def stats(self):
        with self._lock:
            pending = sum(1 for j in self._queue if j.get("target") is None)
            reserved = sum(1 for j in self._queue if j.get("target") is not None)
            return {
                "queue_len": len(self._queue),
                "pending": pending,
                "reserved": reserved,
                "dispatched": dict(self._dispatched),
            }
