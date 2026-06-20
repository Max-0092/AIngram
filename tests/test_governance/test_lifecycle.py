"""sf8a Task 3 — operator governance lifecycle: approve / deny / supersede.

deny AND supersede both revoke any pin (sf7 carry-over): a denied or superseded
entry must not linger in the always-in-context core tier. All three are admin-only;
supersede reuses the 'deny' RBAC permission (no 'supersede' key exists, and the
authorizer fail-opens on unknown tool names — frozen sf1 RBAC).
"""

import pytest

from aingram.core_tier import pin
from aingram.exceptions import AuthorizationError
from aingram.governance.lifecycle import approve, deny, supersede
from aingram.security.auth import CallerContext
from aingram.security.roles import Role
from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def _c(role):
    return CallerContext(agent_id='a', session_id='s', role=role)


def _approved_entry(store):
    eid = store.remember('a fact')
    store._engine.set_governance(eid, status='approved', trust_score=0.9)
    return eid


def test_deny_sets_status_and_clears_pin(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    eid = _approved_entry(store)
    pin(store, eid, caller=_c(Role.ADMIN))
    deny(store, eid, caller=_c(Role.ADMIN))
    entry = store._engine.get_entry(eid)
    assert entry.status == 'denied'
    assert entry.pinned == 0  # denial revokes core-tier membership
    store.close()


def test_non_admin_cannot_deny(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    eid = _approved_entry(store)
    with pytest.raises(AuthorizationError):
        deny(store, eid, caller=_c(Role.READER))
    store.close()


def test_approve_sets_status(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    eid = store.remember('a pending fact')  # defaults to pending
    approve(store, eid, caller=_c(Role.ADMIN))
    assert store._engine.get_entry(eid).status == 'approved'
    store.close()


def test_supersede_sets_valid_to_and_unpins(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    eid = _approved_entry(store)
    pin(store, eid, caller=_c(Role.ADMIN))
    supersede(store, eid, caller=_c(Role.ADMIN))
    entry = store._engine.get_entry(eid)
    assert entry.valid_to is not None  # bi-temporal invalidation
    assert entry.pinned == 0  # superseded → leaves the core tier
    store.close()
