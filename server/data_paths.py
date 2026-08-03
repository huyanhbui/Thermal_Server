"""Resolve the server data directory and migrate one legacy SQLite database.

Run this module through ``prepare_database_path`` before opening TelemetryStore.
It never merges or deletes databases: ambiguity is an operator action, not a
guess the Host may make while handling telemetry.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence


DATA_DIR_ENV = "THERMAL_DATA_DIR"
DATABASE_FILENAME = "telemetry.db"


class DataMigrationConflict(RuntimeError):
    """More than one non-empty database would need to be selected or merged."""


def resolve_data_dir(
        *, env: Mapping[str, str] | None = None,
        local_appdata: str | None = None) -> str:
    """Return the absolute deterministic data directory without creating it."""
    values = os.environ if env is None else env
    explicit = (values.get(DATA_DIR_ENV) or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    base = (local_appdata or values.get("LOCALAPPDATA")
            or values.get("APPDATA") or os.getcwd())
    return os.path.abspath(os.path.join(base, "ThermalOrchestrator", "data"))


def database_path(*, env: Mapping[str, str] | None = None,
                  local_appdata: str | None = None) -> str:
    """Return the canonical telemetry path without touching the filesystem."""
    return os.path.join(resolve_data_dir(env=env, local_appdata=local_appdata),
                        DATABASE_FILENAME)


def _is_nonempty_file(path: str) -> bool:
    """Distinguish a real SQLite history from an empty SQLite shell.

    SQLite creates a non-zero header as soon as a connection opens. Treating
    that header as history would make a first launch conflict with a genuine
    legacy database, so inspect known tables before falling back to byte size
    for non-SQLite legacy fixtures.
    """
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
    except OSError:
        return False
    try:
        db = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
        try:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            for (name,) in tables:
                if name.startswith("sqlite_"):
                    continue
                if db.execute(f'SELECT 1 FROM "{name.replace(chr(34), chr(34) * 2)}" '
                              "LIMIT 1").fetchone() is not None:
                    return True
            return False
        finally:
            db.close()
    except sqlite3.Error:
        # Retain the conservative treatment for a legacy file that has not yet
        # been recognised as SQLite; silently replacing it would lose data.
        return True


def _copy_atomically(source: str, destination: str) -> None:
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".telemetry-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def prepare_database_path(
        *, env: Mapping[str, str] | None = None,
        local_appdata: str | None = None,
        legacy_paths: Sequence[str] = ()) -> str:
    """Choose the canonical DB, copying exactly one legacy source if required.

    A pre-existing non-empty canonical DB wins only when it is the only source.
    Any other combination of non-empty files raises DataMigrationConflict so no
    operational history is silently discarded or merged incorrectly.
    """
    destination = database_path(env=env, local_appdata=local_appdata)
    canonical = os.path.normcase(os.path.abspath(destination))
    candidates: list[str] = []
    seen: set[str] = set()
    for path in (destination, *legacy_paths):
        absolute = os.path.abspath(path)
        identity = os.path.normcase(absolute)
        if _is_nonempty_file(absolute) and identity not in seen:
            candidates.append(absolute)
            seen.add(identity)
    if len(candidates) > 1:
        raise DataMigrationConflict(
            "Phát hiện nhiều telemetry.db có dữ liệu; hãy sao lưu và chọn "
            "một nguồn trước khi khởi động Host.")
    if not candidates:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        return destination
    source = candidates[0]
    if os.path.normcase(source) != canonical:
        # Windows cannot replace an existing SQLite shell even when it has no
        # rows. This file was explicitly classified as empty above, so remove
        # only that disposable shell before the atomic copy of the real DB.
        if os.path.exists(destination) and not _is_nonempty_file(destination):
            os.unlink(destination)
        _copy_atomically(source, destination)
    return destination
