"""Tunnel manager — không giả enabled; stub process."""
import os
os.environ["POC_NO_BACKGROUND"] = "1"

from room import Room
from tunnel import TunnelManager


class FakeProc:
    def __init__(self, lines=None):
        self._lines = list(lines or [])
        self.stdout = iter(self._lines)
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self._rc = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._rc = -9


def test_enable_missing_binary_raises():
    room = Room(room_code="X")
    room.set_password("strong-password-ok", allow_shared=True)
    room.credentials_weak = False
    tm = TunnelManager(which=lambda _: None, require_strong=False)
    try:
        tm.enable(room)
        assert False, "expected ApiError"
    except Exception as e:
        from errors import ApiError
        assert isinstance(e, ApiError)
        assert e.status == 503
    assert tm.status()["enabled"] is False


def test_enable_weak_credentials_blocked():
    room = Room(room_code="X")
    room.set_password("local-dev-password", allow_shared=True)
    room.credentials_weak = True
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared", require_strong=True)
    try:
        tm.enable(room)
        assert False
    except Exception as e:
        from errors import ApiError
        assert isinstance(e, ApiError)
        assert e.code == "FORBIDDEN"


def test_enable_with_stub_popen_sets_enabled():
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok")
    room.set_admin_password("admin-pass-ok")
    room.credentials_weak = False

    def fake_popen(args, **kwargs):
        return FakeProc(lines=[
            "inf: https://abc-def.trycloudflare.com\n"])

    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=fake_popen,
        require_strong=False,
        readiness_probe=lambda _: True,
    )
    st = tm.enable(room)
    assert st["enabled"] is True
    assert st["mode"] == "quick"
    tm.disable()
    assert tm.status()["enabled"] is False


def test_quick_tunnel_uses_an_empty_owned_profile_not_user_config(monkeypatch):
    """Quick Tunnel không được bị config.yaml cá nhân làm hỏng."""
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    room.credentials_weak = False
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return FakeProc(lines=["https://profile.trycloudflare.com\n"])

    monkeypatch.setenv("USERPROFILE", r"C:\\Users\\Operator")
    tm = TunnelManager(which=lambda _: "/fake/cloudflared",
                       popen=fake_popen, require_strong=False,
                       readiness_probe=lambda _: True)
    tm.enable(room, mode="quick")

    profile = captured["env"]["USERPROFILE"]
    assert captured["args"] == ["/fake/cloudflared", "tunnel", "--url",
                                "http://127.0.0.1:8000"]
    assert profile != r"C:\\Users\\Operator"
    assert captured["env"]["HOME"] == profile
    assert captured["env"]["APPDATA"] == profile
    assert os.path.isdir(os.path.join(profile, ".cloudflared"))
    tm.disable()
    assert not os.path.exists(profile)


def test_double_enable_does_not_deadlock():
    import threading
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok")
    room.set_admin_password("admin-pass-ok")
    room.credentials_weak = False

    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(lines=["https://double.trycloudflare.com\n"]),
        require_strong=False,
        readiness_probe=lambda _: True,
    )
    assert tm.enable(room)["enabled"] is True
    done = {"ok": False}

    def second():
        st = tm.enable(room)
        done["ok"] = st["enabled"] is True

    t = threading.Thread(target=second)
    t.start()
    t.join(timeout=2.0)
    assert not t.is_alive(), "double enable deadlocked"
    assert done["ok"] is True
    tm.disable()


def test_named_tunnel_token_not_on_argv():
    """A1: token named tunnel chỉ qua env, không argv."""
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    room.credentials_weak = False
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["env"] = kwargs.get("env") or {}
        return FakeProc()

    secret = "cf-secret-token-should-not-be-argv"
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=fake_popen,
        require_strong=False,
        token=secret,
        hostname="thermal.example.test",
        readiness_probe=lambda _: True,
    )
    tm.enable(room, mode="named", hostname="thermal.example.test")
    joined = " ".join(captured["args"])
    assert "--token" not in captured["args"]
    assert secret not in joined
    assert captured["env"].get("TUNNEL_TOKEN") == secret
    assert captured["args"][:3] == ["/fake/cloudflared", "tunnel", "run"]
    tm.disable()


def test_tunnel_rejects_password_shorter_than_12():
    """A2: tunnel cần mật khẩu ≥12 dù join cho phép ≥8."""
    from errors import ApiError
    room = Room(room_code="X")
    room.set_worker_password("short8ch")  # 8
    room.set_admin_password("also8chr")  # 8
    room.credentials_weak = False
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: FakeProc(),
        require_strong=False,
    )
    try:
        tm.enable(room)
        assert False, "expected FORBIDDEN"
    except ApiError as e:
        assert e.status == 403
        assert "12" in e.message
    assert tm.status()["enabled"] is False


def test_enable_fails_when_public_https_probe_never_succeeds():
    """Invite chỉ được trả sau probe HTTPS; URL stdout đơn thuần chưa đủ."""
    from errors import ApiError

    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok12")
    room.set_admin_password("admin-pass-ok12")
    room.credentials_weak = False
    proc = FakeProc(lines=["https://not-ready.trycloudflare.com\n"])
    audits = []
    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=lambda *a, **k: proc,
        require_strong=False,
        readiness_probe=lambda _: False,
        startup_timeout_s=1,
        audit=lambda event, detail: audits.append((event, detail)),
    )

    try:
        tm.enable(room, mode="quick")
        assert False, "expected readiness timeout"
    except ApiError as exc:
        assert exc.code == "TUNNEL_START_TIMEOUT"

    assert tm.status()["state"] == "failed"
    assert proc.poll() == 0
    assert any(event == "tunnel_failed" for event, _ in audits)
