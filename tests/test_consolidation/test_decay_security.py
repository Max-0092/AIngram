"""sf6 Task 2 — decay as a security sanitizer (trust/status-aware).

Decay is no longer pure Ebbinghaus hygiene: denied and low-trust entries lose
importance faster than a clean one of equal age, so poisoning attempts sink. A clean
approved high-trust entry keeps today's value (factor ≈ 1.0), and an *unscored*
(trust_score=None) entry is not penalized — no signal, no acceleration — which also
keeps existing decay behavior intact.
"""

from aingram.consolidation.decay import compute_decay


def test_low_trust_decays_faster_than_high_trust():
    base = dict(access_count=0, hours_since_access=100.0, importance=0.8)
    clean = compute_decay(trust_score=0.95, status='approved', **base)
    suspicious = compute_decay(trust_score=0.1, status='pending', **base)
    assert suspicious < clean  # suspicious entries sink faster


def test_denied_decays_hardest():
    base = dict(access_count=0, hours_since_access=100.0, importance=0.8)
    denied = compute_decay(trust_score=0.5, status='denied', **base)
    approved = compute_decay(trust_score=0.5, status='approved', **base)
    assert denied < approved


def test_unscored_keeps_ebbinghaus_baseline():
    # No trust signal and no explicit status ⇒ factor 1.0 ⇒ identical to pre-sf6 decay.
    base = dict(access_count=0, hours_since_access=100.0, importance=0.8)
    assert compute_decay(**base) == compute_decay(trust_score=None, status='approved', **base)
