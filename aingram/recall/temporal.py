from __future__ import annotations
from aingram.types import MemoryEntry


def is_valid_at(entry: MemoryEntry, as_of: str | None) -> bool:
    """True if the entry's bi-temporal validity window contains `as_of`.
    as_of=None means 'valid now' = not yet invalidated (valid_to is None)."""
    if as_of is None:
        return entry.valid_to is None
    if entry.valid_from is not None and entry.valid_from > as_of:
        return False
    return entry.valid_to is None or entry.valid_to > as_of
