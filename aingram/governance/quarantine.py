"""Quarantine-by-default: the source/caller -> default ``status`` rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aingram.security.roles import Role

if TYPE_CHECKING:
    from aingram.security.auth import CallerContext

APPROVED, PENDING = 'approved', 'pending'


def default_status_for_caller(caller: 'CallerContext | None') -> str:
    """Quarantine-by-default: only an authenticated ADMIN is auto-approved.

    Keyed off the *authenticated* role, never a self-declared source string —
    otherwise an autonomous caller claims operator identity (impersonation).
    """
    if caller is not None and getattr(caller, 'role', None) == Role.ADMIN:
        return APPROVED
    return PENDING
