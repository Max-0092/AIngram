from __future__ import annotations
from aingram.security.bounds import sanitize_for_prompt
from aingram.types import MemoryEntry

def spotlight(entry: MemoryEntry) -> dict:
    """Wrap a recalled entry as DATA with provenance + trust. The content is passed
    through sanitize_for_prompt so embedded text cannot act as instructions."""
    return {
        'entry_id': entry.entry_id,
        'content': sanitize_for_prompt(entry.content),
        'source': entry.source,
        'status': entry.status,
        'trust_score': entry.trust_score,
        'role': 'data',
    }
