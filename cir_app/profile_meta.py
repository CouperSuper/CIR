from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .paths import ProfilePaths


@dataclass(frozen=True)
class ProfileInfo:
    slug: str
    name: str
    export_path: Path


def metadata_path(paths: ProfilePaths) -> Path:
    return paths.profile_dir / "profile.json"


def ensure_profile_metadata(paths: ProfilePaths, name: str) -> None:
    path = metadata_path(paths)
    payload = {"slug": paths.slug, "name": name or paths.slug}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if existing.get("slug") == paths.slug and existing.get("name") == payload["name"]:
            return
        existing.update(payload)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_profile_name(paths: ProfilePaths) -> str:
    path = metadata_path(paths)
    if not path.exists():
        return paths.slug
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return paths.slug
    return payload.get("name") or paths.slug


def list_profiles(root: Path) -> list[ProfileInfo]:
    profiles_root = root / "profiles"
    if not profiles_root.exists():
        return []
    result = []
    for profile_dir in sorted(path for path in profiles_root.iterdir() if path.is_dir()):
        paths = ProfilePaths(root=root, slug=profile_dir.name)
        result.append(ProfileInfo(profile_dir.name, read_profile_name(paths), paths.export_path))
    return result
