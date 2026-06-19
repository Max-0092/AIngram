"""Shared fixtures for the core-tier tests.

A real ``MemoryStore`` over a tmp DB; entries are governed straight through the
frozen ``engine.set_governance`` (the same write path pin/unpin use), so these
fixtures exercise production plumbing, not a mock.
"""

import pytest

from aingram.security.auth import CallerContext
from aingram.security.roles import Role
from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def _caller(role: Role) -> CallerContext:
    return CallerContext(agent_id=f'{role.value}-1', session_id='s', role=role)


@pytest.fixture
def admin_caller() -> CallerContext:
    return _caller(Role.ADMIN)


@pytest.fixture
def reader_caller() -> CallerContext:
    return _caller(Role.READER)


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    yield s
    s.close()


def _remember_governed(store, text, *, status, trust, pinned=0):
    """remember() then set the v10 governance columns the eligibility policy reads."""
    eid = store.remember(text)
    store._engine.set_governance(eid, status=status, trust_score=trust, pinned=pinned)
    return eid


@pytest.fixture
def store_with_approved_entry(store):
    eid = _remember_governed(store, 'approved high-trust fact', status='approved', trust=0.9)
    return store, eid


@pytest.fixture
def store_with_pending_entry(store):
    eid = _remember_governed(store, 'unreviewed fact', status='pending', trust=0.9)
    return store, eid


@pytest.fixture
def store_with_pinned_entry(store):
    eid = _remember_governed(store, 'already pinned fact', status='approved', trust=0.9, pinned=1)
    return store, eid


@pytest.fixture
def store_with_two_pinned(store):
    _remember_governed(store, 'pinned fact A', status='approved', trust=0.95, pinned=1)
    _remember_governed(store, 'pinned fact B', status='approved', trust=0.85, pinned=1)
    return store


@pytest.fixture
def store_with_one_pinned_one_not(store):
    pinned_id = _remember_governed(store, 'pinned fact', status='approved', trust=0.9, pinned=1)
    other_id = _remember_governed(store, 'archival fact', status='approved', trust=0.9, pinned=0)
    return store, pinned_id, other_id
