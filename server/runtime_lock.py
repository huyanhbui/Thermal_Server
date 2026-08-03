"""Cross-process guard that permits exactly one Host per data directory.

``HostInstanceLock`` keeps an OS-level byte lock for the whole server
lifetime.  The small PID file is only diagnostic: ownership comes from the
open handle, so a stale file after a crash never permanently blocks recovery.
"""
from __future__ import annotations

import os


class HostInstanceAlreadyRunning(RuntimeError):
    """The selected data directory already has an active Host process."""


class HostInstanceLock:
    """Own an exclusive lock file until ``release`` is called."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._file = None

    def acquire(self) -> None:
        """Acquire the runtime lock or raise without altering another Host."""
        if self._file is not None:
            return
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                if os.path.getsize(self.path) == 0:
                    handle.write(b"\0")
                    handle.flush()
                    handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise HostInstanceAlreadyRunning(
                "Thermal Orchestrator Host đang chạy với cùng thư mục dữ liệu."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
        self._file = handle

    def release(self) -> None:
        """Release only the lock acquired by this object and remove its marker."""
        handle = self._file
        if handle is None:
            return
        self._file = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

