# The governed capture gate: every autonomous capture is frisked for secrets,
# trust-scored, and quarantine-stamped (pending) — never auto-approved.
from aingram.capture.gate import evaluate_capture


def test_clean_autonomous_capture_is_pending_not_approved():
    d = evaluate_capture('we decided to use RRF fusion', source='claude_code')
    assert d.allow is True
    assert d.status == 'pending'          # quarantine-by-default
    assert 0.0 <= d.trust_score <= 1.0
    assert d.source == 'claude_code'


def test_secret_hit_blocks_the_write():
    d = evaluate_capture('export R2_SECRET_ACCESS_KEY=' + 'A' * 48, source='claude_code')
    assert d.allow is False               # blocked, not stored
    assert d.trust_score == 0.0
    assert 'secret' in d.reason.lower()


def test_no_path_yields_approved_for_autonomous():
    for src in ('claude_code', 'codex', 'cursor'):
        assert evaluate_capture('hello', source=src).status != 'approved'
