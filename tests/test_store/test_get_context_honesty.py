"""sf8a Task 7 — honesty round-trip: the integrated base, end to end.

Not a unit: remember → pin(admin) → get_context shows the pinned entry (sanitized);
deny(admin) → get_context no longer shows it. Proves the carry-overs wired together —
core-tier injection at get_context (Task 2), the deny lifecycle, and unpin-on-deny
(Task 3) — actually drive each other in production, not just in isolation
([[feedback_wired_not_tested]]).
"""

from aingram.core_tier import pin
from aingram.governance.lifecycle import deny
from aingram.security.auth import CallerContext
from aingram.security.roles import Role
from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def _admin():
    return CallerContext(agent_id='op', session_id='op', role=Role.ADMIN)


def test_pin_then_deny_round_trip_through_get_context(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    eid = store.remember('critical runbook step about deployment')
    store._engine.set_governance(eid, status='approved', trust_score=0.9)

    pin(store, eid, caller=_admin())
    ctx = store.get_context('deployment')
    assert 'runbook' in ctx  # pinned → injected
    assert '<user-content>' in ctx  # spotlighted at egress

    deny(store, eid, caller=_admin())
    ctx2 = store.get_context('deployment')
    # deny unpinned it (gone from core) AND set status='denied' (withheld from recall)
    assert 'runbook' not in ctx2
    store.close()
