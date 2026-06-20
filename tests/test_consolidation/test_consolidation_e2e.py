"""sf6 Task 5 — e2e: dreaming invalidates the stale fact, recall reflects it (Seam F→B→C).

Two contradicting facts about one entity → store.consolidate() (the full dreaming cycle:
decay + contradiction + dormant merge/synth) with a stubbed contradiction classifier →
recall(as_of=None) returns only the current truth, while recall(as_of=<before>) still
returns both (bi-temporal invalidation, not deletion — the audit trail survives).

The stub is injected by monkeypatching _build_contradiction_classifier (store.consolidate
builds its classifier from config, so this is how a no-model stub reaches it). The entity
link is established directly (deterministic) rather than via GLiNER extraction — sf5 covers
extraction; this test's unique job is the contradiction→valid_to→temporal-recall chain.
"""

from datetime import UTC, datetime

import aingram.store as store_mod
from aingram.store import MemoryStore
from aingram.types import ContradictionVerdict
from tests.conftest import MockEmbedder


class _AlwaysContradicts:
    # superseded_index=None ⇒ _resolve_verdict's recency fallback supersedes the OLDER
    # entry (earlier created_at), deterministically regardless of candidate-pair order
    # (get_entity_entry_pairs has no ORDER BY). Semantics: the older fact is the outdated one.
    def classify(self, text_a, text_b):
        return ContradictionVerdict(contradicts=True, confidence=1.0)


def test_dreaming_invalidates_stale_fact_and_recall_reflects_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store_mod, '_build_contradiction_classifier', lambda config: _AlwaysContradicts()
    )
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    old = store.remember('The endpoint runs model X.')
    new = store.remember('The endpoint runs model Y, not X.')
    ent = store._engine.upsert_entity(name='endpoint', entity_type='service')
    store._engine.link_entity_to_mention(ent, old)
    store._engine.link_entity_to_mention(ent, new)

    t_before = datetime.now(UTC).isoformat()
    store.consolidate()  # dreaming: stub contradiction → valid_to stamped on `old`

    now_ids = {r.entry.entry_id for r in store.recall('endpoint', verify=False)}
    assert new in now_ids  # current truth recalled
    assert old not in now_ids  # superseded fact excluded from "recall now"

    past_ids = {r.entry.entry_id for r in store.recall('endpoint', as_of=t_before, verify=False)}
    assert old in past_ids and new in past_ids  # history preserved (audit trail)
    store.close()
