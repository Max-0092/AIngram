# Pin the typed extraction seam (Seam E): any extractor returning a typed
# ExtractionResult satisfies the MemoryExtractor Protocol — so the extractor is
# swappable (GLiNER -> richer labels -> dormant LLM) behind one interface.
from aingram.extraction.protocol import MemoryExtractor
from aingram.types import ExtractionResult


class _Stub:
    def extract(self, text: str) -> ExtractionResult:
        return ExtractionResult(
            entry_type='observation', confidence=0.5, relevance=0.5,
            entities=[], relationships=[],
        )


def test_stub_satisfies_protocol():
    assert isinstance(_Stub(), MemoryExtractor)


def test_result_is_typed_not_dict():
    r = _Stub().extract('hi')
    assert isinstance(r, ExtractionResult)
    assert hasattr(r, 'entities') and hasattr(r, 'relationships')
