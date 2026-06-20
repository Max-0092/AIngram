# End-to-end F13-gap closure at the graph/traversal level: before draining the
# extraction queue, the graph is empty and traversal finds nothing; after
# store.drain_extraction(), remembered entries are linked to extracted entities
# and GraphTraversal.search returns them (recall's graph arm now contributes).
from aingram.graph.traversal import GraphTraversal
from aingram.store import MemoryStore
from aingram.types import ExtractedEntity, ExtractionResult
from tests.conftest import MockEmbedder


class _StubExtractor:
    _ENTS = [
        ExtractedEntity(name='RunPod', entity_type='service', score=0.9),
        ExtractedEntity(name='LTX-2', entity_type='model', score=0.9),
    ]

    def extract(self, text: str) -> ExtractionResult:
        return ExtractionResult('observation', 0.5, 0.5, entities=list(self._ENTS), relationships=[])

    def extract_full(self, text: str) -> ExtractionResult:
        return ExtractionResult('observation', 0.5, 0.5, entities=list(self._ENTS), relationships=[])


def test_drained_captures_enrich_graph_and_traversal(tmp_path):
    store = MemoryStore(str(tmp_path / 'm.db'), embedder=MockEmbedder(), extractor=_StubExtractor())
    store.set_extractor(_StubExtractor())
    engine = store._engine

    id1 = store.remember('first note about the RunPod pipeline')
    id2 = store.remember('second note: the LTX-2 model run')
    query = 'RunPod endpoint and the LTX-2 model'

    # Before the drain the graph is empty -> traversal returns nothing.
    assert GraphTraversal(engine).search(query) == []

    processed = store.drain_extraction()
    assert processed >= 2                      # one extract_entities_v3 task per remembered entry

    # After the drain both entries are linked to the extracted entities, so a
    # query naming those entities traverses back to both source entries.
    found = set(GraphTraversal(engine).search(query))
    assert id1 in found and id2 in found
    store.close()
