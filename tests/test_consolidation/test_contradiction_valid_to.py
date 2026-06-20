"""sf6 Task 1 — contradiction resolution sets valid_to (bi-temporal invalidation).

Today detect_and_resolve only demotes importance; sf3's temporal recall gate has
nothing to act on. The marquee sf6 wire: a resolved contradiction stamps the
superseded entry's valid_to (Seam F→B), so recall(as_of=None) excludes it while
recall(as_of=<past>) still returns it — supersession, not deletion.
"""

from aingram.consolidation.contradiction import ContradictionDetector
from aingram.store import MemoryStore
from aingram.types import ContradictionVerdict
from tests.conftest import MockEmbedder


class _AlwaysContradicts:
    # Real classifier shape (verified vs types.py): classify(text_a, text_b) returns a
    # ContradictionVerdict. confidence has NO default, so it must be supplied.
    # superseded_index=0 → ordered[0] (the first-linked entry) is superseded.
    def classify(self, text_a, text_b):
        return ContradictionVerdict(contradicts=True, confidence=1.0, superseded_index=0)


def test_resolved_contradiction_sets_valid_to(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    a = store.remember('The endpoint runs model X.')
    b = store.remember('The endpoint runs model Y, not X.')
    # Both entries must share an entity so they form a candidate pair
    # (detect_and_resolve groups by get_entity_entry_pairs).
    ent = store._engine.upsert_entity(name='endpoint', entity_type='service')
    store._engine.link_entity_to_mention(ent, a)
    store._engine.link_entity_to_mention(ent, b)

    det = ContradictionDetector(store._engine, classifier=_AlwaysContradicts())
    det.detect_and_resolve()

    assert store._engine.get_entry(a).valid_to is not None  # superseded → invalidated
    assert store._engine.get_entry(b).valid_to is None  # winner still valid
    store.close()
