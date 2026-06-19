# The real F13 gap is operational: with the capture daemon OFF, nothing drives
# the extraction queue. worker.drain() already works — what's missing is a
# PRODUCTION entry point. This RED targets that missing store method, not
# drain() itself (which would pass today = a phantom RED).
from aingram.store import MemoryStore
from aingram.types import ExtractedEntity, ExtractionResult
from tests.conftest import MockEmbedder


class _StubExtractor:
    """Plays both extractor roles: single-arg extract() for remember's type
    inference, and extract_full() for the worker's graph extraction."""

    _ENTS = [
        ExtractedEntity(name='RunPod', entity_type='service', score=0.9),
        ExtractedEntity(name='LTX-2', entity_type='model', score=0.9),
    ]

    def extract(self, text: str) -> ExtractionResult:
        return ExtractionResult(
            entry_type='observation', confidence=0.5, relevance=0.5,
            entities=list(self._ENTS), relationships=[],
        )

    def extract_full(self, text: str) -> ExtractionResult:
        return ExtractionResult(
            entry_type='observation', confidence=0.5, relevance=0.5,
            entities=list(self._ENTS), relationships=[],
        )


def _store_with_stub(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder(), extractor=_StubExtractor())
    store.set_extractor(_StubExtractor())   # exercise the production set_extractor path
    return store


def test_store_drain_extraction_populates_graph_without_a_daemon(tmp_path):
    store = _store_with_stub(tmp_path)
    store.remember('RunPod endpoint ep-123 ran the LTX-2 model')  # enqueues extract_entities_v3
    processed = store.drain_extraction()                          # the production entry point under test
    assert processed >= 1
    ents = store.entities                                          # property, not a method
    names = {e['name'] if isinstance(e, dict) else e.name for e in ents}
    assert any('RunPod' in n or 'LTX' in n for n in names)
    store.close()
