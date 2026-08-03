"""Phòng: mã phòng, băm mật khẩu worker/admin riêng, token có trạng thái.

Token stateful (ADR-002) — thu hồi được khi kick. Không dùng JWT.
Danh tính node suy ra từ token, không bao giờ từ query/body.
Admin không lấy được bằng mật khẩu worker.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field

from errors import ApiError

log = logging.getLogger("room")

PBKDF2_ITERATIONS = 600_000
TOKEN_BYTES = 32
TOKEN_TTL_S = 24 * 3600.0
JOIN_FAIL_LIMIT_PER_MIN = 5
JOIN_FAIL_BACKOFF_AFTER = 3
JOIN_BACKOFF_CAP_S = 300.0
ROOM_CAPACITY = 10
# Token worker không /leave (kill -9): cho join lại cùng tên sau khoảng im lặng.
NODE_RECLAIM_AFTER_S = 90.0
NODE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
AUTH_FAILED_MSG = "Mã phòng hoặc mật khẩu không đúng."


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class TokenRecord:
    token_hash: str
    role: str                 # worker | admin
    node: str | None
    expires_at: float
    revoked: bool = False
    last_seen: float = 0.0
    generation: int = 0


@dataclass
class AuthContext:
    role: str
    node: str | None
    token_hash: str
    generation: int = 0


@dataclass
class Room:
    """Một phòng = một cụm. Lưu token trong RAM (PoC); hash mật khẩu bền."""
    room_code: str
    capacity: int = ROOM_CAPACITY
    salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    worker_password_hash: bytes | None = None
    admin_password_hash: bytes | None = None
    # Đánh dấu credential mặc định yếu (chặn tunnel khi POC_REQUIRE_STRONG_ROOM)
    credentials_weak: bool = False
    allow_tunnel_flag: bool = False
    display_name: str = ""
    # Chỉ lưu độ dài — không lưu plaintext (để enforce tunnel ≥12)
    worker_password_len: int = 0
    admin_password_len: int = 0
    # Tăng mỗi lần close/reopen/đổi MK — token cũ hết hiệu lực
    generation: int = 0
    _tokens: dict[str, TokenRecord] = field(default_factory=dict)
    _nodes: dict[str, str] = field(default_factory=dict)  # node -> token_hash
    _fail_ts: dict[str, list[float]] = field(default_factory=dict)
    _fail_streak: dict[str, int] = field(default_factory=dict)
    _backoff_until: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # Test seam: callable() giữa validate và phát token (giữ/nhả lock trong hook)
    _join_mid_hook: object | None = field(default=None, repr=False)

    def set_worker_password(self, password: str) -> None:
        with self._lock:
            self._set_worker_password_unlocked(password)

    def _set_worker_password_unlocked(self, password: str) -> None:
        if len(password) < 8:
            raise ApiError(400, "BAD_REQUEST",
                           "Mật khẩu phải có ít nhất 8 ký tự.")
        digest = _hash_password(password, self.salt)
        if (self.admin_password_hash is not None
                and hmac.compare_digest(digest, self.admin_password_hash)):
            raise ApiError(400, "BAD_REQUEST",
                           "Mật khẩu worker không được trùng mật khẩu admin.")
        self.worker_password_hash = digest
        self.worker_password_len = len(password)

    def set_admin_password(self, password: str) -> None:
        with self._lock:
            self._set_admin_password_unlocked(password)

    def _set_admin_password_unlocked(self, password: str) -> None:
        if len(password) < 8:
            raise ApiError(400, "BAD_REQUEST",
                           "Mật khẩu phải có ít nhất 8 ký tự.")
        digest = _hash_password(password, self.salt)
        if (self.worker_password_hash is not None
                and hmac.compare_digest(digest, self.worker_password_hash)):
            raise ApiError(400, "BAD_REQUEST",
                           "Mật khẩu admin không được trùng mật khẩu worker.")
        self.admin_password_hash = digest
        self.admin_password_len = len(password)

    def set_password(self, password: str, *, allow_shared: bool = False) -> None:
        """Đặt cùng mật khẩu worker+admin — chỉ khi allow_shared=True (test)."""
        if not allow_shared:
            raise ApiError(
                400, "BAD_REQUEST",
                "Không đặt cùng mật khẩu worker/admin. "
                "Dùng set_worker_password + set_admin_password riêng, "
                "hoặc allow_shared=True (chỉ test).")
        if len(password) < 8:
            raise ApiError(400, "BAD_REQUEST",
                           "Mật khẩu phải có ít nhất 8 ký tự.")
        digest = _hash_password(password, self.salt)
        with self._lock:
            self.worker_password_hash = digest
            self.admin_password_hash = digest
            self.worker_password_len = len(password)
            self.admin_password_len = len(password)

    def has_password(self) -> bool:
        return (self.worker_password_hash is not None
                and self.admin_password_hash is not None)

    def passwords_meet_tunnel_min(self, min_len: int = 12) -> bool:
        """Đủ dài để bật tunnel (docs/06 §3)."""
        return (self.has_password()
                and self.worker_password_len >= min_len
                and self.admin_password_len >= min_len)

    def regenerate_code(self) -> str:
        """Sinh mã THERMAL-XXXX mới."""
        self.room_code = "THERMAL-" + secrets.token_hex(2).upper()
        return self.room_code

    def verify_worker_password(self, password: str) -> bool:
        if self.worker_password_hash is None:
            return False
        digest = _hash_password(password, self.salt)
        return hmac.compare_digest(digest, self.worker_password_hash)

    def verify_admin_password(self, password: str) -> bool:
        if self.admin_password_hash is None:
            return False
        digest = _hash_password(password, self.salt)
        return hmac.compare_digest(digest, self.admin_password_hash)

    def can_enable_tunnel(self, allow_tunnel: bool = True) -> bool:
        """S9 + IT kill-switch: cần mật khẩu VÀ allow_tunnel=true."""
        return self.has_password() and bool(allow_tunnel)

    def enable_tunnel(self) -> None:
        if not self.has_password():
            raise ApiError(
                403, "FORBIDDEN",
                "Không thể bật tunnel khi chưa đặt mật khẩu phòng.")
        self.allow_tunnel_flag = True

    def worker_count(self, now: float) -> int:
        with self._lock:
            return sum(1 for t in self._tokens.values()
                       if t.role == "worker" and not t.revoked
                       and t.expires_at > now)

    @staticmethod
    def _rate_key(ip: str, role: str) -> str:
        """Worker spam không khóa bucket admin cùng IP (và ngược lại)."""
        return f"{ip}|{role}"

    def _prune_fails(self, key: str, now: float) -> list[float]:
        window = [t for t in self._fail_ts.get(key, []) if now - t < 60.0]
        self._fail_ts[key] = window
        return window

    def _check_join_rate(self, key: str, now: float) -> None:
        until = self._backoff_until.get(key, 0.0)
        if now < until:
            raise ApiError(
                429, "RATE_LIMITED",
                "Quá nhiều lần thử. Thử lại sau.",
                retry_after_s=until - now)
        fails = self._prune_fails(key, now)
        if len(fails) >= JOIN_FAIL_LIMIT_PER_MIN:
            raise ApiError(
                429, "RATE_LIMITED",
                "Quá nhiều lần thử. Thử lại sau.",
                retry_after_s=60.0 - (now - fails[0]))

    def _record_fail(self, key: str, now: float) -> None:
        self._fail_ts.setdefault(key, []).append(now)
        streak = self._fail_streak.get(key, 0) + 1
        self._fail_streak[key] = streak
        if streak >= JOIN_FAIL_BACKOFF_AFTER:
            exp = streak - JOIN_FAIL_BACKOFF_AFTER
            delay = min(JOIN_BACKOFF_CAP_S, 2.0 ** (exp + 1))
            self._backoff_until[key] = now + delay

    def _record_success(self, key: str) -> None:
        self._fail_streak[key] = 0
        self._backoff_until.pop(key, None)
        self._fail_ts.pop(key, None)

    def join(self, *, room_code: str, password: str, node_name: str | None,
             role: str, ip: str, now: float | None = None,
             store_audit=None) -> tuple[str, float]:
        """Trả (token_plaintext, expires_at). Ghi audit qua callback."""
        now = time.time() if now is None else now
        if role not in ("worker", "admin"):
            raise ApiError(400, "BAD_REQUEST", "role phải là worker|admin.")
        rate_key = self._rate_key(ip, role)
        with self._lock:
            gen_seen = self.generation
            self._check_join_rate(rate_key, now)

            # Luôn chạy đủ PBKDF2 cho cả hai hash — chống timing oracle (S8).
            code_ok = hmac.compare_digest(room_code, self.room_code)
            worker_digest = _hash_password(password, self.salt)
            admin_digest = _hash_password(password, self.salt)
            worker_ok = (self.worker_password_hash is not None
                         and hmac.compare_digest(
                             worker_digest, self.worker_password_hash))
            admin_ok = (self.admin_password_hash is not None
                        and hmac.compare_digest(
                            admin_digest, self.admin_password_hash))
            if role == "worker":
                hash_ok = worker_ok
            else:
                hash_ok = admin_ok
            ok = code_ok and hash_ok
            if not ok:
                self._record_fail(rate_key, now)
                if store_audit:
                    store_audit(now, ip, "join_failed",
                                {"reason": "AUTH_FAILED"})
                raise ApiError(401, "AUTH_FAILED", AUTH_FAILED_MSG)

            # Seam test: nhả lock để lifecycle chen vào giữa validate và phát token
            if self._join_mid_hook is not None:
                hook = self._join_mid_hook
                self._lock.release()
                try:
                    hook()
                finally:
                    self._lock.acquire()
                if self.generation != gen_seen:
                    self._record_fail(rate_key, now)
                    raise ApiError(
                        401, "AUTH_FAILED",
                        "Phòng đã đổi trong lúc đăng nhập. Thử lại.")
                # Mật khẩu có thể đã bị xóa/đổi — xác thực lại
                worker_ok2 = (self.worker_password_hash is not None
                              and hmac.compare_digest(
                                  worker_digest, self.worker_password_hash))
                admin_ok2 = (self.admin_password_hash is not None
                             and hmac.compare_digest(
                                 admin_digest, self.admin_password_hash))
                hash_ok2 = worker_ok2 if role == "worker" else admin_ok2
                if not (hmac.compare_digest(room_code, self.room_code)
                        and hash_ok2):
                    self._record_fail(rate_key, now)
                    raise ApiError(401, "AUTH_FAILED", AUTH_FAILED_MSG)

            if role == "worker":
                if not node_name or not node_name.strip():
                    raise ApiError(400, "BAD_REQUEST",
                                   "Thiếu node_name cho worker.")
                node_name = node_name.strip()
                if not NODE_NAME_RE.match(node_name):
                    raise ApiError(
                        400, "BAD_REQUEST",
                        "Tên node chỉ gồm chữ, số, '.', '_', '-' "
                        "(1–64 ký tự).")
                live = [t for t in self._tokens.values()
                        if t.role == "worker" and not t.revoked
                        and t.expires_at > now
                        and t.generation == self.generation]
                taken = next((t for t in live if t.node == node_name), None)
                if taken is not None:
                    age = now - (taken.last_seen or 0.0)
                    if age >= NODE_RECLAIM_AFTER_S:
                        taken.revoked = True
                        if self._nodes.get(node_name) == taken.token_hash:
                            del self._nodes[node_name]
                        log.info(
                            "[ROOM] reclaim stale node=%s age=%.0fs",
                            node_name, age)
                        live = [t for t in self._tokens.values()
                                if t.role == "worker" and not t.revoked
                                and t.expires_at > now
                                and t.generation == self.generation]
                    else:
                        raise ApiError(
                            409, "NODE_NAME_TAKEN",
                            f"Tên node '{node_name}' đã có trong phòng.")
                if len(live) >= self.capacity:
                    raise ApiError(
                        409, "ROOM_FULL",
                        "Phòng đã đủ máy.",
                        detail={"capacity": self.capacity,
                                "current": len(live)},
                        retry_after_s=60)
            else:
                node_name = None

            token = urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).decode(
                "ascii").rstrip("=")
            th = _hash_token(token)
            expires = now + TOKEN_TTL_S
            self._tokens[th] = TokenRecord(
                token_hash=th, role=role, node=node_name,
                expires_at=expires, last_seen=now,
                generation=self.generation)
            if node_name:
                self._nodes[node_name] = th
            self._record_success(rate_key)
            if store_audit:
                store_audit(now, ip, "join_ok",
                            {"role": role, "node_name": node_name})
            log.info("[ROOM] join ok role=%s node=%s ip=%s gen=%d",
                     role, node_name or "-", ip, self.generation)
            return token, expires

    def resolve(self, bearer: str | None, now: float | None = None) -> AuthContext:
        now = time.time() if now is None else now
        if not bearer:
            raise ApiError(401, "AUTH_FAILED", "Thiếu token xác thực.")
        th = _hash_token(bearer)
        with self._lock:
            rec = self._tokens.get(th)
            if rec is None:
                raise ApiError(401, "AUTH_FAILED", "Token không hợp lệ.")
            if rec.revoked:
                raise ApiError(401, "TOKEN_REVOKED", "Token đã bị thu hồi.")
            if rec.generation != self.generation:
                raise ApiError(401, "TOKEN_REVOKED",
                               "Token thuộc phòng cũ (generation đổi).")
            if rec.expires_at <= now:
                raise ApiError(401, "TOKEN_EXPIRED", "Token đã hết hạn.")
            rec.last_seen = now
            rec.expires_at = max(rec.expires_at, now + TOKEN_TTL_S)
            return AuthContext(role=rec.role, node=rec.node, token_hash=th,
                               generation=rec.generation)

    def token_alive(self, token_hash: str, generation: int,
                    now: float | None = None) -> bool:
        """True nếu token còn sống đúng generation hiện tại."""
        now = time.time() if now is None else now
        with self._lock:
            rec = self._tokens.get(token_hash)
            if rec is None or rec.revoked:
                return False
            if rec.generation != self.generation or generation != self.generation:
                return False
            return rec.expires_at > now

    def leave(self, auth: AuthContext, now: float | None = None,
              store_audit=None, ip: str = "") -> None:
        now = time.time() if now is None else now
        with self._lock:
            rec = self._tokens.get(auth.token_hash)
            if rec:
                rec.revoked = True
                if rec.node and self._nodes.get(rec.node) == auth.token_hash:
                    del self._nodes[rec.node]
            if store_audit:
                store_audit(now, ip, "leave",
                            {"node_name": auth.node, "role": auth.role})
            log.info("[ROOM] leave node=%s", auth.node or auth.role)

    def kick(self, node: str, now: float | None = None,
             store_audit=None, ip: str = "") -> None:
        now = time.time() if now is None else now
        with self._lock:
            th = self._nodes.get(node)
            if th is None:
                raise ApiError(404, "NOT_FOUND", f"Không thấy node '{node}'.")
            rec = self._tokens.get(th)
            if rec:
                rec.revoked = True
            self._nodes.pop(node, None)
            if store_audit:
                store_audit(now, ip, "kick", {"node_name": node})
            log.info("[ROOM] kick node=%s", node)

    def _revoke_all_unlocked(self, now: float, store_audit=None,
                             ip: str = "") -> int:
        n = 0
        for rec in self._tokens.values():
            if not rec.revoked:
                rec.revoked = True
                n += 1
        self._nodes.clear()
        if store_audit:
            store_audit(now, ip, "room_closed", {"revoked": n})
        return n

    def revoke_all_tokens(self, now: float | None = None,
                          store_audit=None, ip: str = "") -> int:
        """Đóng phòng: thu hồi mọi token (docs/10 §1 vòng đời)."""
        now = time.time() if now is None else now
        with self._lock:
            n = self._revoke_all_unlocked(now, store_audit=store_audit, ip=ip)
            log.info("[ROOM] đóng phòng — thu hồi %d token", n)
            return n

    def clear_passwords(self) -> None:
        """Xóa hash mật khẩu (sau khi đóng phòng — cần bootstrap lại)."""
        with self._lock:
            self._clear_passwords_unlocked()

    def _clear_passwords_unlocked(self) -> None:
        self.worker_password_hash = None
        self.admin_password_hash = None
        self.worker_password_len = 0
        self.admin_password_len = 0
        self.allow_tunnel_flag = False

    def lifecycle_close(self, now: float,
                        store_audit=None, ip: str = "") -> int:
        """Atomic: bump generation + revoke + clear passwords (một lần giữ lock).

        `now` bắt buộc từ caller — không đọc đồng hồ tường nội bộ (bất biến 7).
        """
        with self._lock:
            self.generation += 1
            n = self._revoke_all_unlocked(now, store_audit=store_audit, ip=ip)
            self._clear_passwords_unlocked()
            log.info("[ROOM] lifecycle_close gen=%d revoked=%d",
                     self.generation, n)
            return n

    def lifecycle_rotate_passwords(
            self, worker_password: str, admin_password: str,
            now: float, store_audit=None, ip: str = "") -> int:
        """Atomic: bump generation + revoke + đặt MK mới (không cửa sổ join chen).

        `now` bắt buộc từ caller — không đọc đồng hồ tường nội bộ (bất biến 7).
        """
        with self._lock:
            self.generation += 1
            n = self._revoke_all_unlocked(now, store_audit=store_audit, ip=ip)
            self._set_worker_password_unlocked(worker_password)
            self._set_admin_password_unlocked(admin_password)
            log.info("[ROOM] lifecycle_rotate gen=%d revoked=%d",
                     self.generation, n)
            return n

    def force_expire(self, token_plaintext: str, expires_at: float) -> None:
        """Test helper: set expiry on an existing token."""
        th = _hash_token(token_plaintext)
        with self._lock:
            rec = self._tokens.get(th)
            if rec:
                rec.expires_at = expires_at


def make_default_room(room_code: str = "THERMAL-LOCAL",
                      worker_password: str = "local-dev-password",
                      admin_password: str | None = None,
                      *,
                      credentials_weak: bool = True) -> Room:
    """Tạo phòng test/PoC. admin_password mặc định khác worker."""
    if admin_password is None:
        admin_password = "local-admin-password"
    room = Room(room_code=room_code, credentials_weak=credentials_weak)
    room.set_worker_password(worker_password)
    room.set_admin_password(admin_password)
    return room
