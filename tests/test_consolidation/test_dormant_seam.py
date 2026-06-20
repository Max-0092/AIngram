"""sf6 Task 3 — Ollama merge + knowledge-synthesis are present but dormant by default.

PIN-EXISTING-BEHAVIOR (not a RED): verified against the fork, MemoryMerger.merge_similar
and KnowledgeSynthesizer.synthesize both early-return zeroed results when self._llm is
None (merger.py:65-66, knowledge.py:118-119), and store.consolidate(*, llm=None) passes
llm straight through. So consolidate() with no llm already yields zero merges/syntheses.
This test locks that contract (the DoD "dormant by default") — manufacturing a failing
RED here would be the phantom-RED trap. Decay + contradiction stay unconditional.
"""

from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def test_merge_and_synthesis_are_off_by_default(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder())
    store.remember('a')
    store.remember('b')
    r = store.consolidate()  # no llm, default config
    assert r.memories_merged == 0
    assert r.summaries_created == 0
    assert r.knowledge_synthesized == 0  # dormant: no Ollama ⇒ no synthesis
    store.close()
