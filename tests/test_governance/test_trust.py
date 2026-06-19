from aingram.governance.trust import TrustSignals, compute_trust_score


def _s(**kw):
    base = dict(source_trust=1.0, provenance_valid=True, secret_hits=0, anomaly_score=0.0)
    base.update(kw)
    return TrustSignals(**base)


def test_clean_operator_entry_scores_high():
    assert compute_trust_score(_s()) == 1.0


def test_secret_hit_forces_zero():           # hard block dominates
    assert compute_trust_score(_s(secret_hits=1)) == 0.0


def test_invalid_provenance_halves_trust():  # forgery / broken signature
    assert compute_trust_score(_s(provenance_valid=False)) == 0.5


def test_anomaly_scales_trust_down():        # flooding / outlier
    assert compute_trust_score(_s(anomaly_score=0.5)) == 0.5


def test_low_source_trust_caps_score():      # impersonation / unknown origin
    assert compute_trust_score(_s(source_trust=0.3)) == 0.3


def test_score_is_clamped_to_unit_interval():
    assert compute_trust_score(_s(source_trust=2.0)) == 1.0
    assert compute_trust_score(_s(anomaly_score=5.0)) == 0.0
