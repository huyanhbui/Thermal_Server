"""Quản lý Cloudflare Tunnel với trạng thái sẵn sàng có thể kiểm chứng.

Quick Tunnel dùng cho demo; Named Tunnel cần hostname và token. Token chỉ đi
qua biến môi trường của tiến trình cloudflared, không xuất hiện trên argv,
status, log hay audit. Module không xử lý HTTP route: server.py gọi ``is_ready``
trước khi phát invite URL và chỉ gọi ``touch_activity`` cho request qua tunnel.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from errors import ApiError

log = logging.getLogger("tunnel")

URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")
BACKOFF_START_S = 5.0
BACKOFF_CAP_S = 300.0
IDLE_TIMEOUT_S = 8 * 3600.0
STARTUP_TIMEOUT_S = 30.0
HEALTH_PROBE_EVERY_S = 20.0
TUNNEL_MIN_PASSWORD_LEN = 12
TUNNEL_STATES = frozenset({
    "disabled", "starting", "ready", "degraded", "failed", "stopping",
})
TUNNEL_WARNING = (
    "Bật tunnel sẽ đưa phòng này ra Internet công cộng. Dùng mật khẩu mạnh "
    "(≥12 ký tự) và tắt tunnel khi không dùng."
)


class TunnelManager:
    def __init__(self, *, local_url: str = "http://127.0.0.1:8000",
                 binary: str | None = None, token: str | None = None,
                 popen: Callable = subprocess.Popen,
                 which: Callable = shutil.which,
                 require_strong: bool | None = None,
                 allow_tunnel: bool = True,
                 idle_timeout_s: float = IDLE_TIMEOUT_S,
                 clock: Callable[[], float] | None = None,
                 hostname: str | None = None,
                 readiness_probe: Callable[[str], bool] | None = None,
                 startup_timeout_s: float = STARTUP_TIMEOUT_S,
                 audit: Callable[[str, dict], None] | None = None):
        self.local_url = local_url
        self._binary_override = binary
        self._token = token if token is not None else os.environ.get(
            "CLOUDFLARED_TOKEN")
        self._hostname = (hostname or "").strip().lower() or None
        self._popen = popen
        self._which = which
        self._require_strong = (require_strong if require_strong is not None
                                else os.environ.get(
                                    "POC_REQUIRE_STRONG_ROOM", "1") == "1")
        self._allow_tunnel = bool(allow_tunnel)
        self._idle_timeout_s = float(idle_timeout_s)
        self._clock = clock or time.time
        self._readiness_probe = readiness_probe
        self._startup_timeout_s = max(1.0, float(startup_timeout_s))
        self._audit = audit
        self._proc = None
        self._lock = threading.Lock()
        self._enabled = False
        self._state = "disabled"
        self._mode: str | None = None
        self._public_url: str | None = None
        self._last_error: str | None = None
        self._reconnect_attempt = 0
        self._stop = threading.Event()
        self._thread = None
        self._starting = False
        self._last_activity_at: float | None = None
        self._quick_profile_dir: str | None = None
        self._ready_event = threading.Event()
        self._last_health_probe_at = 0.0

    def configure(self, *, mode: str, hostname: str | None = None,
                  token: str | None = None) -> None:
        """Cấu hình trước khi enable; token chỉ giữ trong RAM của Host."""
        if mode not in ("quick", "named"):
            raise ApiError(400, "BAD_REQUEST", "mode phải là quick hoặc named.")
        host = (hostname or "").strip().lower() or None
        if mode == "named" and not host:
            raise ApiError(400, "BAD_REQUEST",
                           "Named Tunnel cần hostname công khai.")
        with self._lock:
            if self._enabled:
                raise ApiError(409, "CONFLICT",
                               "Tắt tunnel trước khi đổi cấu hình.")
            self._mode = mode
            self._hostname = host
            if token is not None:
                self._token = token

    def set_allow_tunnel(self, allowed: bool) -> None:
        self._allow_tunnel = bool(allowed)
        if not self._allow_tunnel and self._enabled:
            log.warning("[TUNNEL] allow_tunnel=false — tắt tunnel đang chạy")
            self.disable(event_type="tunnel_disabled")

    def touch_activity(self, now: float | None = None) -> None:
        """Chỉ server.py được gọi hàm này sau khi xác nhận request qua tunnel."""
        t = self._clock() if now is None else float(now)
        with self._lock:
            if self._enabled:
                self._last_activity_at = t

    def _resolve_binary(self) -> str | None:
        if self._binary_override:
            return self._binary_override
        return os.environ.get("CLOUDFLARED_PATH") or self._which("cloudflared")

    def _audit_event(self, event_type: str, detail: dict | None = None) -> None:
        if self._audit is None:
            return
        safe = dict(detail or {})
        for key in ("token", "secret", "password", "authorization"):
            safe.pop(key, None)
        try:
            self._audit(event_type, safe)
        except Exception:
            log.exception("[TUNNEL] audit callback failed event=%s", event_type)

    def _status_unlocked(self) -> dict:
        return {
            "enabled": self._enabled,
            "state": self._state,
            "mode": self._mode,
            "public_url": self._public_url,
            "hostname": self._hostname,
            "last_error": self._last_error,
            "reconnect_attempt": self._reconnect_attempt,
            "allow_tunnel": self._allow_tunnel,
            "warning": TUNNEL_WARNING if self._enabled else None,
            "last_activity_at": self._last_activity_at,
            "idle_timeout_s": self._idle_timeout_s,
        }

    def status(self) -> dict:
        with self._lock:
            return self._status_unlocked()

    def is_ready(self) -> bool:
        with self._lock:
            return self._enabled and self._state == "ready"

    def check_idle(self, now: float | None = None) -> bool:
        t = self._clock() if now is None else float(now)
        with self._lock:
            if not self._enabled or self._last_activity_at is None:
                return False
            if t - self._last_activity_at < self._idle_timeout_s:
                return False
        self.disable(event_type="tunnel_idle_disabled")
        return True

    def enable(self, room, *, mode: str | None = None,
               hostname: str | None = None) -> dict:
        if not self._allow_tunnel:
            raise ApiError(403, "FORBIDDEN",
                           "Tunnel đã bị vô hiệu hóa (allow_tunnel=false).")
        if not room.has_password():
            raise ApiError(403, "FORBIDDEN",
                           "Không thể bật tunnel khi chưa đặt mật khẩu phòng.")
        if (hasattr(room, "passwords_meet_tunnel_min")
                and not room.passwords_meet_tunnel_min(TUNNEL_MIN_PASSWORD_LEN)):
            raise ApiError(403, "FORBIDDEN",
                           "Mật khẩu worker và admin phải ≥12 ký tự trước khi bật tunnel.")
        if self._require_strong and getattr(room, "credentials_weak", False):
            raise ApiError(403, "FORBIDDEN",
                           "Không bật tunnel với credential mặc định yếu.")
        binary = self._resolve_binary()
        if not binary:
            raise ApiError(503, "TUNNEL_UNAVAILABLE",
                           "Không tìm thấy cloudflared (CLOUDFLARED_PATH hoặc PATH).")
        explicit_mode = mode is not None
        requested_mode = mode or self._mode or ("named" if self._token else "quick")
        requested_host = (hostname or self._hostname or "").strip().lower() or None
        if requested_mode not in ("quick", "named"):
            raise ApiError(400, "BAD_REQUEST", "mode phải là quick hoặc named.")
        if requested_mode == "named" and not self._token:
            raise ApiError(400, "BAD_REQUEST", "Named Tunnel cần token.")
        if requested_mode == "named" and explicit_mode and not requested_host:
            raise ApiError(400, "BAD_REQUEST", "Named Tunnel cần hostname công khai.")
        self._audit_event("tunnel_enable_requested", {
            "mode": requested_mode, "hostname": requested_host})
        with self._lock:
            if self._enabled and self._proc is not None:
                return self._status_unlocked()
            if self._starting:
                return self._status_unlocked()
            self._starting = True
            self._enabled = True
            self._state = "starting"
            self._mode = requested_mode
            self._hostname = requested_host
            self._public_url = None
            self._last_error = None
            self._last_activity_at = self._clock()
            self._ready_event.clear()
            self._stop.clear()
        try:
            self._start_process(binary, requested_mode)
        except ApiError:
            with self._lock:
                self._enabled = False
                self._state = "failed"
                self._proc = None
                self._starting = False
                self._last_activity_at = None
            self._cleanup_quick_profile()
            self._audit_event("tunnel_failed", {"mode": requested_mode})
            raise
        with self._lock:
            self._starting = False
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._supervise, args=(binary,), daemon=True)
            self._thread.start()
        if requested_mode == "named" and requested_host:
            public_url = f"https://{requested_host}"
            with self._lock:
                self._public_url = public_url
            self._set_public_readiness(public_url)
        if not self._ready_event.wait(self._startup_timeout_s):
            self._fail_startup("Không xác nhận được URL HTTPS công khai kịp thời.")
            raise ApiError(503, "TUNNEL_START_TIMEOUT",
                           "Tunnel chưa sẵn sàng; hãy kiểm tra cloudflared và Internet.")
        room.enable_tunnel()
        return self.status()

    def disable(self, *, event_type: str = "tunnel_disabled") -> dict:
        self._stop.set()
        with self._lock:
            self._state = "stopping" if self._enabled else "disabled"
            old_mode = self._mode
            self._enabled = False
            self._starting = False
            self._kill_unlocked()
            self._public_url = None
            self._mode = None
            self._reconnect_attempt = 0
            self._last_activity_at = None
            self._state = "disabled"
            out = self._status_unlocked()
        self._cleanup_quick_profile()
        self._audit_event(event_type, {"mode": old_mode})
        log.info("[TUNNEL] disabled")
        return out

    def _kill_unlocked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _fail_startup(self, message: str) -> None:
        self._stop.set()
        with self._lock:
            mode = self._mode
            self._enabled = False
            self._starting = False
            self._state = "failed"
            self._last_error = message
            self._public_url = None
            self._last_activity_at = None
            self._kill_unlocked()
        self._cleanup_quick_profile()
        self._audit_event("tunnel_failed", {"mode": mode,
                                             "code": "TUNNEL_START_TIMEOUT"})

    def _start_process(self, binary: str, mode: str) -> None:
        env = os.environ.copy()
        if mode == "named":
            args = [binary, "tunnel", "run"]
            env["TUNNEL_TOKEN"] = self._token
        else:
            args = [binary, "tunnel", "--url", self.local_url]
            # Quick Tunnels fail when cloudflared discovers the operator's
            # ~/.cloudflared/config.yml. Give this child an empty, owned home;
            # do not touch, rename or depend on the user's configuration.
            profile = self._quick_profile()
            env["HOME"] = profile
            env["USERPROFILE"] = profile
            env["APPDATA"] = profile
        try:
            proc = self._popen(args, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1,
                               env=env)
        except OSError as e:
            with self._lock:
                self._last_error = "Không chạy được cloudflared."
            raise ApiError(503, "TUNNEL_UNAVAILABLE",
                           "Không chạy được cloudflared.") from e
        with self._lock:
            self._proc = proc
        if mode == "quick" and proc.stdout is not None:
            threading.Thread(target=self._read_quick_stdout,
                             args=(proc,), daemon=True).start()

    def _quick_profile(self) -> str:
        with self._lock:
            if self._quick_profile_dir is None:
                profile = tempfile.mkdtemp(prefix="thermal-quick-")
                os.makedirs(os.path.join(profile, ".cloudflared"), exist_ok=True)
                self._quick_profile_dir = profile
            return self._quick_profile_dir

    def _cleanup_quick_profile(self) -> None:
        with self._lock:
            profile, self._quick_profile_dir = self._quick_profile_dir, None
        if not profile:
            return
        try:
            shutil.rmtree(profile)
        except OSError:
            log.warning("[TUNNEL] không dọn được quick profile tạm")

    def _read_quick_stdout(self, proc) -> None:
        try:
            for line in proc.stdout:
                match = URL_RE.search(line or "")
                if match:
                    with self._lock:
                        if self._public_url is not None:
                            continue
                        self._public_url = match.group(0)
                    self._set_public_readiness(match.group(0))
        except Exception:
            with self._lock:
                self._last_error = "Không đọc được trạng thái cloudflared."

    def _set_public_readiness(self, public_url: str) -> None:
        ready = self._probe_public(public_url)
        with self._lock:
            if not self._enabled:
                return
            self._state = "ready" if ready else "degraded"
            self._last_error = None if ready else "Không xác nhận được URL công khai."
            if ready:
                self._ready_event.set()
        self._audit_event("tunnel_enabled" if ready else "tunnel_degraded", {
            "mode": self._mode, "public_url": public_url})

    def _probe_public(self, public_url: str) -> bool:
        try:
            if self._readiness_probe is not None:
                return bool(self._readiness_probe(public_url))
            request = Request(public_url, method="HEAD")
            with urlopen(request, timeout=5.0) as response:
                return 200 <= getattr(response, "status", 200) < 500
        except (OSError, URLError, ValueError):
            return False

    def _supervise(self, binary: str) -> None:
        backoff = BACKOFF_START_S
        while not self._stop.is_set():
            with self._lock:
                proc, enabled, mode = self._proc, self._enabled, self._mode
            if not enabled:
                return
            if proc is None:
                time.sleep(0.5)
                continue
            rc = proc.poll()
            if rc is None:
                time.sleep(1.0)
                backoff = BACKOFF_START_S
                continue
            with self._lock:
                self._last_error = f"cloudflared exited rc={rc}"
                self._state = "degraded"
                self._reconnect_attempt += 1
                # A Quick Tunnel receives a new random URL after reconnect.
                # Never keep advertising the previous, now-dead URL.
                self._proc = None
                self._public_url = None
                self._ready_event.clear()
            self._audit_event("tunnel_degraded", {"reason": "process_exit"})
            if self._stop.wait(backoff):
                return
            try:
                self._start_process(binary, mode or "quick")
                if mode == "named":
                    with self._lock:
                        hostname = self._hostname
                    if hostname:
                        public_url = f"https://{hostname}"
                        with self._lock:
                            self._public_url = public_url
                        self._set_public_readiness(public_url)
                if not self._ready_event.wait(self._startup_timeout_s):
                    with self._lock:
                        self._last_error = (
                            "Tunnel kết nối lại nhưng URL HTTPS chưa sẵn sàng.")
                        self._state = "degraded"
                        self._kill_unlocked()
                    self._audit_event("tunnel_degraded", {
                        "reason": "reconnect_readiness_timeout"})
                else:
                    self._audit_event("tunnel_reconnected", {"mode": mode})
            except ApiError as e:
                with self._lock:
                    self._state = "failed"
                    self._last_error = e.message
                self._audit_event("tunnel_failed", {"code": e.code})
            backoff = min(BACKOFF_CAP_S, backoff * 2)
