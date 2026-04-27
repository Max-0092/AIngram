from __future__ import annotations

from typing import Protocol, runtime_checkable

from aingram.types import ExtractionResult


@runtime_checkable
class MemoryExtractor(Protocol):
    """Protocol for memory metadata extraction.

    Note: LocalExtractor migrated to EntityExtractor (aingram.processing.protocols)
    and exposes extract_full() for combined entity+relationship extraction.
    This protocol is retained for SonnetExtractor and external implementations
    that return a full ExtractionResult from a single extract() call.
    """

    def extract(self, text: str) -> ExtractionResult: ...
