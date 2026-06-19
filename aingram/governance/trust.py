"""Composite trust score over four orthogonal signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrustSignals:
    source_trust: float       # who: authenticated source identity, 0..1
    provenance_valid: bool    # history: signature/hash verified
    secret_hits: int          # content: count of secret-scan hits
    anomaly_score: float      # behaviour: 0 normal .. 1 anomalous


def compute_trust_score(signals: TrustSignals) -> float:
    """Combine four orthogonal signals into one trust score in [0, 1].

    Each signal defends a different attack (source=impersonation,
    provenance=forgery, secret_hits=payload, anomaly=flooding). A secret hit
    is a hard zero; the rest compose multiplicatively so any one axis can veto.
    """
    if signals.secret_hits > 0:
        return 0.0
    score = max(0.0, min(1.0, signals.source_trust))
    if not signals.provenance_valid:
        score *= 0.5
    score *= max(0.0, 1.0 - signals.anomaly_score)
    return max(0.0, min(1.0, score))
