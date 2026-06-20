"""Operator governance lifecycle: approve / deny / supersede.

A thin policy layer over the mechanism-only ``engine.set_governance``. ``deny`` and
``supersede`` also revoke any pin — a denied or superseded entry must not stay in the
always-in-context core tier (closes the sf7 carry-over). All three are admin-only.

``supersede`` reuses the ``'deny'`` RBAC permission deliberately: frozen sf1
``PERMISSIONS`` has no ``'supersede'`` key, and ``RoleAuthorizer.check`` fail-OPENS on
an unknown tool name — so passing ``'supersede'`` would gate nobody. Reusing ``'deny'``
keeps the admin gate real without editing the frozen roles table.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aingram.core_tier import unpin
from aingram.security.roles import RoleAuthorizer


def _require(caller, permission: str) -> None:
    """Operator gate: raises ``AuthorizationError`` if ``caller`` lacks ``permission``."""
    RoleAuthorizer().check(caller, permission)


def approve(store, entry_id: str, *, caller) -> None:
    _require(caller, 'approve')
    store._engine.set_governance(entry_id, status='approved')


def deny(store, entry_id: str, *, caller) -> None:
    _require(caller, 'deny')
    store._engine.set_governance(entry_id, status='denied')
    unpin(store, entry_id, caller=caller)  # denial revokes core-tier membership


def supersede(store, entry_id: str, *, caller, valid_to: str | None = None) -> None:
    _require(caller, 'deny')  # supersession is an admin governance op (reuses 'deny' perm)
    store._engine.set_governance(entry_id, valid_to=valid_to or datetime.now(UTC).isoformat())
    unpin(store, entry_id, caller=caller)  # a superseded fact must also leave the core tier
