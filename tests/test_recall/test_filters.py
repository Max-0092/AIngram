# tests/test_recall/test_filters.py — governance facet filter integration tests
"""Verify that recall() honors governance facet filters (source, kind, domain, scope).

These use a real MemoryStore + real SQLite (same pattern as test_recall_integration.py).
set_governance() writes the facet columns; recall(filters={...}) must post-filter on them.
"""
from __future__ import annotations

import pytest

from aingram.config import AIngramConfig
from tests.conftest import MockEmbedder


@pytest.fixture
def store_with_mixed(tmp_path):
    """Return (store, ids) where:
    ids['operator_fact']  — source='operator', kind='fact'
    ids['codex_outcome']  — source='codex',    kind='outcome'
    ids['no_facets']      — no governance attributes set (source=None, kind=None)
    """
    from aingram.store import MemoryStore

    db = tmp_path / "filter_integration.db"
    store = MemoryStore(
        str(db),
        agent_name="test-agent",
        embedder=MockEmbedder(),
        config=AIngramConfig(),
    )

    op_id = store.remember("topic: operator fact entry about the project")
    cx_id = store.remember("topic: codex outcome entry about the project")
    nf_id = store.remember("topic: plain entry with no governance attributes")

    store._engine.set_governance(op_id, source="operator", kind="fact")
    store._engine.set_governance(cx_id, source="codex", kind="outcome")
    # nf_id left with defaults (source=None, kind=None)

    ids = {
        "operator_fact": op_id,
        "codex_outcome": cx_id,
        "no_facets": nf_id,
    }
    yield store, ids
    store.close()


def test_filter_by_source_and_kind(store_with_mixed):
    """recall with source='operator' + kind='fact' returns the matching entry only."""
    store, ids = store_with_mixed
    results = store.recall("topic", filters={"source": "operator", "kind": "fact"}, limit=10)
    got = {r.entry.entry_id for r in results}
    assert ids["operator_fact"] in got
    assert ids["codex_outcome"] not in got


def test_filter_by_source_only(store_with_mixed):
    """recall with only source='codex' returns the codex entry and not the operator entry."""
    store, ids = store_with_mixed
    results = store.recall("topic", filters={"source": "codex"}, limit=10)
    got = {r.entry.entry_id for r in results}
    assert ids["codex_outcome"] in got
    assert ids["operator_fact"] not in got


def test_filter_none_value_does_not_filter(store_with_mixed):
    """A facet key with value None must not filter — entries with any source value are returned."""
    store, ids = store_with_mixed
    # filters={'source': None} must behave as if source filter is absent
    results = store.recall("topic", filters={"source": None}, limit=10)
    got = {r.entry.entry_id for r in results}
    # Both entries with explicit sources must still appear
    assert ids["operator_fact"] in got
    assert ids["codex_outcome"] in got


def test_no_facet_entry_excluded_when_source_filtered(store_with_mixed):
    """An entry with source=None is excluded when source filter is set to a specific value."""
    store, ids = store_with_mixed
    results = store.recall("topic", filters={"source": "operator"}, limit=10)
    got = {r.entry.entry_id for r in results}
    # no_facets has source=None — should not match source='operator'
    assert ids["no_facets"] not in got


def test_type_weights_still_honored_alongside_facet_filter(store_with_mixed):
    """type_weights key in filters must not be interpreted as a facet (no crash, no exclusion)."""
    store, ids = store_with_mixed
    # type_weights is a scoring hint, not a facet — passing it alongside a facet filter must work
    results = store.recall(
        "topic",
        filters={"source": "operator", "kind": "fact", "type_weights": {"fact": 1.5}},
        limit=10,
    )
    got = {r.entry.entry_id for r in results}
    assert ids["operator_fact"] in got
