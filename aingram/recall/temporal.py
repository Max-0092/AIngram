from __future__ import annotations

from datetime import UTC, datetime

from aingram.types import MemoryEntry


def is_valid_at(entry: MemoryEntry, as_of: str | None) -> bool:
    """True if the entry's bi-temporal validity window contains `as_of`.

    as_of=None means 'valid now' = already effective (valid_from has passed) AND not yet
    invalidated (valid_to is None). Honoring valid_from on the default path keeps a
    scheduled-future entry from leaking — symmetric with the explicit-as_of branch and
    fail-closed. ISO-8601 UTC strings compare lexicographically == chronologically."""
    if as_of is None:
        not_future = entry.valid_from is None or entry.valid_from <= datetime.now(UTC).isoformat()
        return not_future and entry.valid_to is None
    if entry.valid_from is not None and entry.valid_from > as_of:
        return False
    return entry.valid_to is None or entry.valid_to > as_of
