# The governed capture gate: every autonomous capture is frisked for secrets,
# trust-scored, and quarantine-stamped (pending) — never auto-approved.
from aingram.capture.config import CaptureConfig
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


def test_secret_block_knob_is_not_a_bypass():
    # Contract lock (pins existing behavior): CaptureConfig.secret_block is a DECLARED
    # knob, but the gate enforces secret-blocking UNCONDITIONALLY — evaluate_capture
    # never consults the config. Turning the knob off must NOT open a bypass.
    # TRIPWIRE: if a future change threads `config` into evaluate_capture, extend this
    # test to pass CaptureConfig(secret_block=False) and assert the write still blocks,
    # so the knob can never silently become a secret-at-rest escape hatch.
    assert CaptureConfig(secret_block=False).secret_block is False   # the knob can be off...
    secret = 'export R2_SECRET_ACCESS_KEY=' + 'A' * 48
    d = evaluate_capture(secret, source='claude_code')               # ...yet the gate still blocks
    assert d.allow is False
    assert d.trust_score == 0.0
