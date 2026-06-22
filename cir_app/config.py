from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .constants import ROLE_SPECIALIST


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


DEFAULT_SERVER_ROOT = app_base_dir() / "server_data"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-zа-яё0-9]+", "_", value, flags=re.IGNORECASE)
    value = value.strip("_")
    return value or "user"


def default_config_path() -> Path:
    override = os.environ.get("CIR_CONFIG_PATH")
    if override:
        return Path(override)
    return app_base_dir() / ".cir_app_config.json"


@dataclass
class AppConfig:
    server_root: str
    user_slug: str
    user_name: str
    role: str = ROLE_SPECIALIST
    active_profile_slug: str = ""

    @classmethod
    def defaults(cls) -> "AppConfig":
        return cls(
            server_root=str(DEFAULT_SERVER_ROOT),
            user_slug="specialist",
            user_name="Специалист стройконтроля",
            role=ROLE_SPECIALIST,
            active_profile_slug="specialist",
        )

    def normalized(self) -> "AppConfig":
        user_slug = slugify(self.user_slug or self.user_name)
        active = slugify(self.active_profile_slug or user_slug)
        return AppConfig(
            server_root=str(Path(self.server_root or DEFAULT_SERVER_ROOT)),
            user_slug=user_slug,
            user_name=(self.user_name or user_slug).strip(),
            role=self.role or ROLE_SPECIALIST,
            active_profile_slug=active,
        )


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        return AppConfig.defaults()
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return AppConfig(**payload).normalized()


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(config.normalized()), handle, ensure_ascii=False, indent=2)
