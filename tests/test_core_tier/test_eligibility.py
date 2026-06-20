# Pin eligibility is a pure policy function: approved + high-trust + under cap,
# and it must fail CLOSED (None trust is NOT eligible, never a default-pass).
from aingram.core_tier import MAX_PINNED, can_pin
from aingram.types import MemoryEntry


def _e(status='approved', trust=0.9):
    return MemoryEntry(
        entry_id='e', content_hash='h', entry_type='observation', content='{}',
        session_id='s', sequence_num=1, prev_entry_id=None, signature='x',
        created_at='2026-01-01T00:00:00+00:00', status=status, trust_score=trust,
    )


def test_approved_high_trust_under_cap_is_eligible():
    ok, _ = can_pin(_e(), current_count=0)
    assert ok is True


def test_pending_is_refused():
    ok, reason = can_pin(_e(status='pending'), current_count=0)
    assert ok is False and 'approved' in reason


def test_low_or_missing_trust_is_refused():
    assert can_pin(_e(trust=0.5), current_count=0)[0] is False
    assert can_pin(_e(trust=None), current_count=0)[0] is False   # fails closed


def test_size_cap_enforced():
    ok, reason = can_pin(_e(), current_count=MAX_PINNED)
    assert ok is False and 'cap' in reason.lower()
