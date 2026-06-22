from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import Actor


LOCK_TTL = timedelta(hours=16)


@dataclass
class LockResult:
    can_write: bool
    message: str
    owned: bool = False


class ProfileLock:
    def __init__(self, path: Path, actor: Actor, session_id: str):
        self.path = path
        self.actor = actor
        self.session_id = session_id
        self.owned = False

    def acquire(self) -> LockResult:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "holder_slug": self.actor.slug,
            "holder_name": self.actor.name,
            "holder_role": self.actor.role,
            "session_id": self.session_id,
            "locked_at": datetime.now().isoformat(timespec="seconds"),
        }
        for _attempt in range(2):
            try:
                _write_lock_exclusive(self.path, payload)
                self.owned = True
                return LockResult(True, "Профиль открыт для редактирования", owned=True)
            except FileExistsError:
                current = _read_lock(self.path)
                locked_at = _parse_dt(current.get("locked_at", ""))
                stale = locked_at is None or datetime.now() - locked_at > LOCK_TTL
                if stale:
                    self.path.unlink(missing_ok=True)
                    continue
                holder = current.get("holder_name") or current.get("holder_slug") or "другой пользователь"
                role = current.get("holder_role") or "пользователь"
                return LockResult(False, f"Профиль уже открыт для записи: {holder} ({role}). Второе окно открыто только для чтения.")
        current = _read_lock(self.path)
        holder = current.get("holder_name") or current.get("holder_slug") or "другой пользователь"
        return LockResult(False, f"Профиль уже открыт для записи: {holder}. Второе окно открыто только для чтения.")

    def release(self) -> None:
        if not self.owned or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if payload.get("session_id") == self.session_id:
            self.path.unlink(missing_ok=True)
        self.owned = False


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _read_lock(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_lock_exclusive(path: Path, payload: dict[str, str]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
    except Exception:
        os.close(descriptor)
        raise
    with handle:
        handle.write(data)
