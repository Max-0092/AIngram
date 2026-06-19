"""Letta-style core memory tier: a small, always-in-context, high-trust working set
— the governed, in-store successor to a hand-kept MEMORY.md.

The analogy (Letta / MemGPT): **core memory = RAM** (a tiny set injected into every
prompt regardless of query) versus **archival memory = disk** (the large store, reached
only by query-driven recall — sf3). This module owns the *core* tier; sf3 owns archival.

Pinning is operator-only and fails closed: an entry may enter core memory only when it is
``approved`` AND high-trust AND the pinned set is under a hard size cap. Pin/unpin are
``admin``-gated via sf1's RBAC. Writes go through the frozen ``engine.set_governance``
``pinned`` column; reads go through the frozen ``engine.get_pinned_entries`` primitive —
this module edits no shared read/write path.
"""

from __future__ import annotations

from aingram.security.roles import RoleAuthorizer
from aingram.types import MemoryEntry

# A pinned entry is always-in-context, so the bar is deliberately high.
PIN_TRUST_THRESHOLD = 0.8
# Hard cap on the working set — core memory is RAM, not the whole store.
MAX_PINNED = 20


def can_pin(entry: MemoryEntry, *, current_count: int) -> tuple[bool, str]:
    """Pure eligibility policy: is ``entry`` allowed into the core tier right now?

    Fails CLOSED — missing/None trust is treated as ineligible, never a default-pass.
    Returns ``(eligible, reason)`` so callers can surface why a pin was refused.
    """
    if entry.status != 'approved':
        return False, 'must be approved to pin'
    if entry.trust_score is None or entry.trust_score < PIN_TRUST_THRESHOLD:
        return False, f'trust below {PIN_TRUST_THRESHOLD}'
    if current_count >= MAX_PINNED:
        return False, 'pinned set at size cap'
    return True, 'ok'


def _require(caller, permission: str) -> None:
    """Operator gate: raises ``AuthorizationError`` if ``caller`` lacks ``permission``.

    Passes the ``CallerContext`` object (not ``caller.role``) — the authorizer owns
    the policy lookup and reaches in for the role itself (frozen sf1 RBAC).
    """
    RoleAuthorizer().check(caller, permission)


def pin(store, entry_id: str, *, caller) -> None:
    """Admin-only: move an eligible entry into the core tier.

    Propagates ``AuthorizationError`` for a non-admin caller; raises ``ValueError``
    if the entry is missing or ineligible (``can_pin`` failed). Writes through the
    frozen ``engine.set_governance`` pinned column — no new write path.
    """
    _require(caller, 'pin')
    entry = store._engine.get_entry(entry_id)
    if entry is None:
        raise ValueError('no such entry')
    ok, reason = can_pin(entry, current_count=len(store._engine.get_pinned_entries()))
    if not ok:
        raise ValueError(reason)
    store._engine.set_governance(entry_id, pinned=1)


def unpin(store, entry_id: str, *, caller) -> None:
    """Admin-only: remove an entry from the core tier (no eligibility check needed)."""
    _require(caller, 'unpin')
    store._engine.set_governance(entry_id, pinned=0)
