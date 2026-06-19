# The capture config exposes governance knobs with fail-safe defaults: capture
# is quarantine-by-default and secret-blocking on, out of the box.
from aingram.capture.config import CaptureConfig


def test_governance_defaults_are_safe():
    c = CaptureConfig()
    assert c.quarantine_default is True   # autonomous writes land pending
    assert c.secret_block is True         # secret-bearing captures are blocked


def test_consolidation_interval_still_present():
    # Pre-existing knob must remain (DoD: auto-consolidation behavior intact).
    assert CaptureConfig().consolidation_interval_records == 50
