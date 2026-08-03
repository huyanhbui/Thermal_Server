"""Test #11 — tunnel stdout drain sau URL."""
import os
import time

os.environ["POC_NO_BACKGROUND"] = "1"

from room import Room
from tunnel import TunnelManager


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line


class FakeProc:
    def __init__(self, lines=None):
        self._lines = list(lines or [])
        self.stdout = FakeStdout(self._lines)
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self._rc = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._rc = -9


def test_tunnel_drains_stdout_after_url():
    room = Room(room_code="X")
    room.set_worker_password("worker-pass-ok")
    room.set_admin_password("admin-pass-ok12")
    room.credentials_weak = False

    lines = [
        "noise line\n",
        "inf: https://abc-def.trycloudflare.com\n",
        "secret-token-should-not-log\n",
        "more output\n",
    ]
    proc = FakeProc(lines=lines)

    def fake_popen(args, **kwargs):
        return proc

    tm = TunnelManager(
        which=lambda _: "/fake/cloudflared",
        popen=fake_popen,
        require_strong=False,
        readiness_probe=lambda _: True,
    )
    tm.enable(room)
    deadline = time.time() + 2.0
    while proc.stdout._i < len(lines) and time.time() < deadline:
        time.sleep(0.05)
    assert proc.stdout._i == len(lines)
    assert tm.status()["public_url"] == "https://abc-def.trycloudflare.com"
    tm.disable()
