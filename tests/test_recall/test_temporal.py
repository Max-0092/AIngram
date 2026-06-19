from aingram.recall.temporal import is_valid_at
from aingram.types import MemoryEntry


def _entry(**kw):
    base = dict(entry_id='e', content_hash='h', entry_type='observation', content='{}',
                session_id='s', sequence_num=1, prev_entry_id=None, signature='x',
                created_at='2026-01-01T00:00:00+00:00')
    base.update(kw)
    return MemoryEntry(**base)


def test_valid_now_default_excludes_invalidated():
    assert is_valid_at(_entry(valid_to=None), None) is True
    assert is_valid_at(_entry(valid_to='2026-03-01T00:00:00+00:00'), None) is False


def test_as_of_point_in_time():
    e = _entry(valid_from='2026-01-01T00:00:00+00:00', valid_to='2026-06-01T00:00:00+00:00')
    assert is_valid_at(e, '2026-03-01T00:00:00+00:00') is True   # inside window
    assert is_valid_at(e, '2026-07-01T00:00:00+00:00') is False  # after valid_to
    assert is_valid_at(e, '2025-12-01T00:00:00+00:00') is False  # before valid_from
