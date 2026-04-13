from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


PERMISSIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ADMIN": (
            "student.create",
            "student.update",
            "student.delete",
            "student.update.course",
            "settings.update",
        ),
        "CLERK": (
            "student.create",
            "student.update",
            "student.delete",
            "student.update.course",
        ),
        # SuperAdmin is constrained by route-level path guards; keep broad permission coverage.
        "SUPERADMIN": (
            "student.create",
            "student.update",
            "student.delete",
            "student.update.course",
            "settings.update",
        ),
    }
)


def permissions_for_role(role: str | None) -> tuple[str, ...]:
    normalized_role = str(role or "").strip().upper()
    return PERMISSIONS.get(normalized_role, ())


def has_permission(user: Any, action: str) -> bool:
    role = getattr(user, "role", None)
    return str(action).strip() in permissions_for_role(role)
