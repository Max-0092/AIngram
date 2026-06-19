"""Governed write gate for the autonomous capture daemon.

This is what makes it safe to turn capture back ON (F13 left it OFF because
nothing screened autonomous writes). Every drained capture passes through here:
a secret hit *blocks* the write; otherwise the entry is trust-scored and
stamped quarantine-by-default (``pending``) — never auto-approved for an
autonomous source. Reuses the frozen sf1 governance primitives; adds no policy
of its own beyond composing them.
"""

from __future__ import annotations

from dataclasses import dataclass

from aingram.governance.quarantine import default_status_for_caller
from aingram.governance.secrets import scan_for_secrets
from aingram.governance.trust import TrustSignals, compute_trust_score


@dataclass(frozen=True)
class GateDecision:
    allow: bool          # False => blocked, never stored
    status: str          # the governance status to stamp if stored
    trust_score: float   # baseline composite trust in [0, 1]
    source: str          # the originating tool (provenance)
    reason: str          # human-readable why


def evaluate_capture(text: str, *, source: str, caller=None) -> GateDecision:
    """Decide whether/how to store one autonomous capture.

    A secret pattern blocks the write (``allow=False``, trust 0.0). Otherwise
    the write is allowed but quarantined: ``default_status_for_caller`` returns
    ``pending`` for a ``None`` caller (autonomous) — only an authenticated
    ADMIN caller could be approved, and the capture path never supplies one.
    """
    hits = scan_for_secrets(text)
    if hits:
        return GateDecision(False, 'denied', 0.0, source, f'secret pattern(s): {len(hits)}')
    signals = TrustSignals(source_trust=0.5, provenance_valid=True, secret_hits=0, anomaly_score=0.0)
    score = compute_trust_score(signals)
    status = default_status_for_caller(caller)   # None caller -> 'pending' (fails closed)
    return GateDecision(True, status, score, source, 'ok')
