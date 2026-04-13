from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


PERMISSIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ADMIN": (
            "student.view",
            "student.create",
            "student.update",
            "student.delete",
            "student.update.course",
            "catalog.view",
            "catalog.manage",
            "payment.view",
            "payment.manage",
            "settings.view",
            "settings.manage",
            "user.view",
            "user.manage",
            "system.manage",
        ),
        "CLERK": (
            "student.view",
            "student.update",
            "student.delete",
            "student.update.course",
            "catalog.view",
            "payment.view",
        ),
        "SUPERADMIN": (
            "student.view",
            "student.create",
            "student.update",
            "student.delete",
            "student.update.course",
            "catalog.view",
            "catalog.manage",
            "payment.view",
            "payment.manage",
            "settings.view",
            "settings.manage",
            "user.view",
            "user.manage",
            "system.manage",
        ),
    }
)


def permissions_for_role(role: str | None) -> tuple[str, ...]:
    normalized_role = str(role or "").strip().upper()
    return PERMISSIONS.get(normalized_role, ())


def has_permission(user: Any, action: str) -> bool:
    role = getattr(user, "role", None)
    return str(action).strip() in permissions_for_role(role)
