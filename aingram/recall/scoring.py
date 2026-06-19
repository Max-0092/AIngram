from __future__ import annotations

_STATUS_WEIGHTS = {'approved': 1.0, 'pending': 0.4, 'denied': 0.0}
_KIND_TO_TYPE = {'fact': 'semantic', 'instruction': 'procedural', 'outcome': 'episodic'}

def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))

def trust_factor(trust_score: float | None) -> float:
    return 0.5 if trust_score is None else _clamp(trust_score)

def status_factor(status: str) -> float:
    return _STATUS_WEIGHTS.get(status, 0.4)

def mem_type_factor(kind: str | None, weights: dict[str, float]) -> float:
    mem_type = _KIND_TO_TYPE.get(kind or '', None)
    if mem_type is None:
        return 1.0
    return weights.get(mem_type, 1.0)

def compose_recall_score(base_score: float, *, trust_score: float | None, status: str,
                         kind: str | None, type_weights: dict[str, float]) -> float:
    return (base_score
            * trust_factor(trust_score)
            * status_factor(status)
            * mem_type_factor(kind, type_weights or {}))
