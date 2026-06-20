"""sf8a Task 4 — set_governance validates status at write time (sf3/sf5 carry-over).

The cluster chose write-time validation over read-time fail-close: a bad status must
never reach the column, so every read path can then trust the column. The valid set is
sf1's frozen enum (pending/approved/denied) — the same set the DB CHECK enforces.
"""

import pytest

from aingram.storage.engine import StorageEngine


def test_set_governance_rejects_unknown_status(tmp_path):
    eng = StorageEngine(str(tmp_path / 'm.db'))
    try:
        with pytest.raises(ValueError):
            eng.set_governance('nonexistent-id', status='approve')  # typo, not in enum
    finally:
        eng.close()


def test_set_governance_accepts_enum_status(tmp_path):
    eng = StorageEngine(str(tmp_path / 'm.db'))
    try:
        for s in ('pending', 'approved', 'denied'):
            eng.set_governance('any-id', status=s)  # no raise (no-op UPDATE on missing id is fine)
    finally:
        eng.close()
