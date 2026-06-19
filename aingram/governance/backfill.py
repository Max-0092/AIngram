"""Lossless metadata -> governance-columns backfill for the existing corpus.

OPERATOR RUN NOTE (the real ~210-entry run is operator-gated; it rides with sf8, NOT sf2):
    1. Stop the recall daemon (it serves the shared data/aingram.db).
    2. cp data/aingram.db data/aingram.db.bak-<date>          # backup first
    3. Run apply_schema(conn) + backfill_governance_columns(conn) on the COPY.
    4. Verify lossless: row count unchanged; spot-check 5 entries; the post-run
       status='approved' count == the pre-run row count.
    5. Only then swap the verified copy in and restart the daemon.
This module is developed and tested on a synthetic fixture only.
"""

from __future__ import annotations

import json
import sqlite3

_KEYS = ('kind', 'source', 'domain', 'scope')


def backfill_governance_columns(conn: sqlite3.Connection) -> int:
    """Map metadata JSON -> governance columns; curate rows approved + baseline trust 1.0 + valid.

    Idempotent. The existing corpus is operator-curated, so rows are defaulted to approved.
    Uses COALESCE so a non-NULL governance value (e.g. a consolidation re-score) is never
    clobbered with NULL on a re-run.
    """
    rows = conn.execute(
        'SELECT entry_id, metadata, created_at FROM memory_entries'
    ).fetchall()
    n = 0
    for entry_id, metadata, created_at in rows:
        meta = {}
        if metadata:
            try:
                meta = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        sets = {k: meta[k] for k in _KEYS if isinstance(meta, dict) and meta.get(k) is not None}
        conn.execute(
            'UPDATE memory_entries SET '
            'kind = COALESCE(?, kind), source = COALESCE(?, source), '
            'domain = COALESCE(?, domain), scope = COALESCE(?, scope), '
            "status = 'approved', trust_score = COALESCE(trust_score, 1.0), "
            'valid_from = COALESCE(valid_from, ?) '
            'WHERE entry_id = ?',
            (sets.get('kind'), sets.get('source'), sets.get('domain'), sets.get('scope'),
             created_at, entry_id),
        )
        n += 1
    conn.commit()
    return n
