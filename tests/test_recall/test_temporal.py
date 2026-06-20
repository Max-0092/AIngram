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


def test_future_valid_from_is_not_valid_now():
    # Fail-closed: a future-dated entry (valid_from ahead of now, not yet invalidated)
    # must NOT leak on the default 'valid now' path — the as_of=None branch was
    # ignoring valid_from, so a scheduled-future entry passed (GLM nit).
    future = '2099-01-01T00:00:00+00:00'
    assert is_valid_at(_entry(valid_from=future, valid_to=None), None) is False
    # An already-effective entry (past valid_from, not invalidated) is still valid now.
    assert is_valid_at(_entry(valid_from='2020-01-01T00:00:00+00:00', valid_to=None), None) is True


def test_as_of_point_in_time():
    e = _entry(valid_from='2026-01-01T00:00:00+00:00', valid_to='2026-06-01T00:00:00+00:00')
    assert is_valid_at(e, '2026-03-01T00:00:00+00:00') is True   # inside window
    assert is_valid_at(e, '2026-07-01T00:00:00+00:00') is False  # after valid_to
    assert is_valid_at(e, '2025-12-01T00:00:00+00:00') is False  # before valid_from
    assert is_valid_at(e, '2026-01-01T00:00:00+00:00') is True   # as_of == valid_from -> inclusive start
    assert is_valid_at(e, '2026-06-01T00:00:00+00:00') is False  # as_of == valid_to   -> exclusive end
