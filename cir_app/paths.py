from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProfilePaths:
    root: Path
    slug: str

    @property
    def profile_dir(self) -> Path:
        return self.root / "profiles" / self.slug

    @property
    def db_path(self) -> Path:
        return self.profile_dir / "cir.sqlite"

    @property
    def export_path(self) -> Path:
        return self.profile_dir / "export.xlsx"

    @property
    def attachments_dir(self) -> Path:
        return self.profile_dir / "attachments"

    @property
    def lock_path(self) -> Path:
        return self.profile_dir / "edit.lock"

    def ensure(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)


def server_root(path: str) -> Path:
    root = Path(path).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def profile_paths(root: Path, slug: str) -> ProfilePaths:
    paths = ProfilePaths(root=root, slug=slug)
    paths.ensure()
    return paths
