"""sf8a Task 5 — recall honors the full Seam C facet set: status + mem_type.

sf3 implemented only source/kind/domain/scope facets; status was just the denied
hard-gate (not a filter to a requested status) and mem_type was a scoring hint, not a
filter. sf8b (yt-automation) can't fix fork code, so closing the seam is sf8a's job.
Per schema-freeze, mem_type is NOT a column — it reverse-maps to kind
(semantic→fact, procedural→instruction, episodic→outcome).
"""

from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def _mk(store, text, *, status, kind):
    eid = store.remember(text)
    store._engine.set_governance(eid, status=status, trust_score=0.9, kind=kind)
    return eid


def test_recall_filters_by_status_and_mem_type(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    _mk(store, 'approved fact about widgets', status='approved', kind='fact')
    _mk(store, 'pending fact about widgets', status='pending', kind='fact')
    _mk(store, 'approved how-to about widgets', status='approved', kind='instruction')

    got = store.recall('widgets', filters={'status': 'approved'})
    assert got and all(r.entry.status == 'approved' for r in got)  # status facet
    got2 = store.recall('widgets', filters={'mem_type': 'semantic'})
    assert got2 and all(r.entry.kind == 'fact' for r in got2)  # mem_type→kind
    store.close()
