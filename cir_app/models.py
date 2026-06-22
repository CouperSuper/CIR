from __future__ import annotations

from dataclasses import dataclass

from .constants import ROLE_SPECIALIST, ROLE_SUBSTITUTE, SOURCE_OWNER, SOURCE_SUBSTITUTE, SOURCE_SUPERVISOR


@dataclass(frozen=True)
class Actor:
    slug: str
    name: str
    role: str
    source_kind: str


def source_kind_for(role: str, user_slug: str, owner_slug: str) -> str:
    if role == ROLE_SPECIALIST and user_slug == owner_slug:
        return SOURCE_OWNER
    if role == ROLE_SUBSTITUTE:
        return SOURCE_SUBSTITUTE
    return SOURCE_SUPERVISOR
