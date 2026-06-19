# tests/test_recall/test_recall_integration.py — integration tests for trust-aware, temporal recall
"""These tests hit a real MemoryStore (real SQLite DB) to prove the new recall behaviour:

1. default recall excludes invalidated (valid_to in the past) entries
2. denied entries are withheld entirely
3. as_of= returns the historical set (entries valid at that timestamp)
"""
from __future__ import annotations

import pytest

from aingram.config import AIngramConfig
from tests.conftest import MockEmbedder


@pytest.fixture
def store_with_entries(tmp_path):
    """Return (store, ids) where:
    ids['cur']    — valid now (valid_to=NULL, status='pending')
    ids['old']    — invalidated in the past (valid_to in early 2026, valid_from=None)
    ids['denied'] — valid_to=NULL but status='denied'
    """
    from aingram.store import MemoryStore

    db = tmp_path / "recall_integration.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )

    # All three entries have the same topic so they'll all be candidates
    cur_id = store.remember("topic: active current entry")
    old_id = store.remember("topic: historical old entry")
    denied_id = store.remember("topic: denied entry withheld")

    # old: was valid from 2025-01-01 to 2026-01-01 (already expired)
    store._engine.set_governance(
        old_id,
        valid_from="2025-01-01T00:00:00+00:00",
        valid_to="2026-01-01T00:00:00+00:00",
    )

    # denied: status='denied' (valid_to=NULL, so temporally valid, but status-gated)
    store._engine.set_governance(denied_id, status="denied")

    ids = {"cur": cur_id, "old": old_id, "denied": denied_id}
    yield store, ids
    store.close()


def test_default_recall_excludes_invalidated(store_with_entries):
    """By default (as_of=None), entries with valid_to in the past are excluded."""
    store, ids = store_with_entries
    results = store.recall("topic", limit=10)
    got = {r.entry.entry_id for r in results}
    assert ids["cur"] in got
    assert ids["old"] not in got  # invalidated — must be excluded


def test_denied_entry_is_withheld(store_with_entries):
    """Entries with status='denied' must not appear in recall results."""
    store, ids = store_with_entries
    results = store.recall("topic", limit=10)
    assert ids["denied"] not in {r.entry.entry_id for r in results}


def test_as_of_returns_historical_set(store_with_entries):
    """as_of= a past timestamp must include entries that were valid then."""
    store, ids = store_with_entries
    # 2026-02-01 is after valid_from=2025-01-01 and before valid_to=2026-01-01 — wait no:
    # valid_to=2026-01-01, and 2026-02-01 > 2026-01-01 so it's expired by then.
    # Use 2025-06-01 which is within [2025-01-01, 2026-01-01).
    results = store.recall("topic", as_of="2025-06-01T00:00:00+00:00", limit=10)
    got = {r.entry.entry_id for r in results}
    assert ids["old"] in got  # was valid at 2025-06-01
