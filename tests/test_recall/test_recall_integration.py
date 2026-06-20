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
    # Use 2025-06-01 which is within [2025-01-01, 2026-01-01).
    results = store.recall("topic", as_of="2025-06-01T00:00:00+00:00", limit=10)
    got = {r.entry.entry_id for r in results}
    assert ids["old"] in got  # was valid at 2025-06-01


# ---------------------------------------------------------------------------
# Regression tests: fast-path quarantine bypass (entry_id and chain_id paths)
# ---------------------------------------------------------------------------

def test_recall_by_entry_id_withholds_denied(tmp_path):
    """recall(entry_id=x) must not return a denied entry — the fast path must honor status gate."""
    from aingram.store import MemoryStore

    db = tmp_path / "fastpath_denied.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )
    try:
        eid = store.remember("secret denied content")
        store._engine.set_governance(eid, status="denied")
        results = store.recall(entry_id=eid)
        assert results == [], f"Expected [], got {results}"
    finally:
        store.close()


def test_recall_by_entry_id_excludes_invalidated_by_default(tmp_path):
    """recall(entry_id=x) must exclude temporally-invalidated entries by default."""
    from aingram.store import MemoryStore

    db = tmp_path / "fastpath_temporal.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )
    try:
        eid = store.remember("once-valid content")
        # Set valid window entirely in the past
        store._engine.set_governance(
            eid,
            valid_from="2025-01-01T00:00:00+00:00",
            valid_to="2026-01-01T00:00:00+00:00",
        )
        # Default (as_of=None = now, 2026-06-19): entry is expired → must be excluded
        results = store.recall(entry_id=eid)
        assert results == [], f"Expected [] for expired entry, got {results}"
        # But as_of inside the valid window must return it
        results_historical = store.recall(entry_id=eid, as_of="2025-06-01T00:00:00+00:00")
        assert len(results_historical) == 1, "Expected entry when querying inside its valid window"
    finally:
        store.close()


def test_recall_by_entry_id_excludes_future_dated_by_default(tmp_path):
    """recall(entry_id=x) must exclude a not-yet-effective (future valid_from) entry
    by default — the fast path must fail closed, not leak scheduled-future entries."""
    from aingram.store import MemoryStore

    db = tmp_path / "fastpath_future.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )
    try:
        eid = store.remember("scheduled-future content")
        # valid_from in the far future, not yet invalidated (valid_to=NULL)
        store._engine.set_governance(eid, valid_from="2099-01-01T00:00:00+00:00")
        # Default (as_of=None = now): entry is not yet effective → must be excluded
        results = store.recall(entry_id=eid)
        assert results == [], f"Expected [] for future-dated entry, got {results}"
        # But as_of after it becomes effective must return it
        later = store.recall(entry_id=eid, as_of="2099-06-01T00:00:00+00:00")
        assert len(later) == 1, "Expected entry when querying after its valid_from"
    finally:
        store.close()


def test_recall_by_chain_withholds_denied(tmp_path):
    """recall(chain_id=x, query=None) must not return denied entries — chain fast path must honor status gate."""
    from aingram.store import MemoryStore

    db = tmp_path / "fastpath_chain.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )
    try:
        chain_id = store.create_chain("test chain")
        good_id = store.remember("good entry in chain", chain_id=chain_id)
        bad_id = store.remember("denied entry in chain", chain_id=chain_id)
        store._engine.set_governance(bad_id, status="denied")
        results = store.recall(chain_id=chain_id)
        ids_returned = {r.entry.entry_id for r in results}
        assert good_id in ids_returned, "Good entry must be returned"
        assert bad_id not in ids_returned, "Denied entry must be withheld from chain fast path"
    finally:
        store.close()
