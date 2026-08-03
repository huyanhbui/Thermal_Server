"""Persist metadata phòng ra room.json — KHÔNG chứa plaintext mật khẩu.

Đường dẫn mặc định: cạnh settings.json, hoặc
%LOCALAPPDATA%/ThermalOrchestrator/config/room.json khi cài bộ installer.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("room")

# Trường được phép ghi — không bao giờ password / hash / salt
_ALLOWED = (
    "role",
    "name",
    "display_name",
    "room_code",
    "site_id",
    "model_id",
    "threshold_c",
    "password_set",
    "tunnel_ready",
    "invite",
    "node_name",
)


def default_room_json_path(settings_path: str | None = None) -> str:
    """Ưu tiên config cạnh settings; fallback LOCALAPPDATA installer."""
    if settings_path:
        base = os.path.dirname(os.path.abspath(settings_path))
        return os.path.join(base, "room.json")
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or "."
    return os.path.join(local, "ThermalOrchestrator", "config", "room.json")


def load_room_meta(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        # Loại bỏ mọi khóa nhạy cảm nếu file cũ còn sót
        for bad in ("password", "worker_password", "admin_password",
                    "password_hash", "salt"):
            data.pop(bad, None)
        return {k: data[k] for k in data if k in _ALLOWED or k.startswith("_")}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("[ROOM] không đọc được %s: %s", path, e)
        return {}


def save_room_meta(path: str, meta: dict[str, Any]) -> None:
    """Ghi metadata an toàn. Từ chối nếu có khóa mật khẩu."""
    clean: dict[str, Any] = {}
    for k, v in meta.items():
        lk = str(k).lower()
        if "password" in lk or lk in ("salt", "token", "secret"):
            continue
        if k in _ALLOWED:
            clean[k] = v
    clean.setdefault("password_set", bool(meta.get("password_set")))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    log.info("[ROOM] đã lưu metadata → %s", path)


def save_room_auth(store, room) -> None:
    """Lưu verifier SQLite của Room; token phiên không bao giờ được chuyển vào DB."""
    store.save_room_auth(
        room_code=room.room_code, salt=room.salt,
        worker_password_hash=room.worker_password_hash,
        admin_password_hash=room.admin_password_hash,
        worker_password_len=room.worker_password_len,
        admin_password_len=room.admin_password_len,
        generation=room.generation,
        credentials_weak=room.credentials_weak,
        display_name=room.display_name,
    )


def load_room_auth(store):
    """Khôi phục Room từ verifier bền; token RAM cũ cố ý không được khôi phục."""
    record = store.load_room_auth()
    if record is None:
        return None
    # Import muộn để room.py tiếp tục độc lập với tầng I/O SQLite.
    from room import Room

    room = Room(
        room_code=record["room_code"], salt=record["salt"],
        credentials_weak=record["credentials_weak"],
        display_name=record["display_name"],
    )
    room.worker_password_hash = record["worker_password_hash"]
    room.admin_password_hash = record["admin_password_hash"]
    room.worker_password_len = record["worker_password_len"]
    room.admin_password_len = record["admin_password_len"]
    room.generation = record["generation"]
    return room
