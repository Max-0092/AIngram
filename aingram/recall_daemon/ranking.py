# aingram/recall_daemon/ranking.py
from __future__ import annotations

from typing import Any

_CONTENT_CAP = 500


def _cap_at_word(text: str, cap: int) -> str:
    """Cap length without splitting a word — a half word in a memory preview
    reads as corruption to both humans and models. The '…' marks that more
    text exists in the stored entry."""
    if len(text) <= cap:
        return text
    cut = text[: cap - 1]  # budget the ellipsis inside the cap
    head, sep, _ = cut.rpartition(' ')
    return (head if sep else cut).rstrip() + '…'


def apply_ranking(
    results: list[dict[str, Any]],
    *,
    cwd: str | None,
    seen: list[str],
    project_boost: float,
    seen_demote: float,
    score_threshold: float,
    limit: int,
    relevance_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Project-boost + seen-demote + threshold filter, in Python (never SQL).

    Input results carry 'entry_id', 'score', 'relevance', 'project_path', etc.
    Returns a new list of dicts with adjusted scores, sorted desc, truncated
    to `limit`, with content capped at 500 chars.

    Two independent cutoffs, because they measure different things:

    * ``score_threshold`` applies to the RRF-fused score. RRF scores *rank
      position*, not similarity — with k=60 the value is a function of where an
      entry placed in each list, so it barely moves with match quality and its
      useful range is corpus-dependent. Treat it as a floor against the tail, not
      as a relevance gate.
    * ``relevance_threshold`` applies to ``relevance``: absolute cosine in 0..1,
      which *does* track match quality (a direct hit ~0.6+, tangential ~0.43).
      This is the meaningful knob for "only inject if it's actually related".

    Defaults to 0.0 (no relevance filtering) so existing deployments keep their
    behaviour. Entries with no ``relevance`` key are never dropped by it — a store
    that cannot compute cosine must not silently return nothing.
    """
    seen_set = set(seen)
    adjusted: list[dict[str, Any]] = []
    for r in results:
        score = float(r.get('score', 0.0))
        if cwd and r.get('project_path') == cwd:
            score += project_boost
        if r.get('entry_id') in seen_set:
            score -= seen_demote
        if score < score_threshold:
            continue
        relevance = r.get('relevance')
        if relevance is not None and float(relevance) < relevance_threshold:
            continue
        out = dict(r)
        out['score'] = score
        content = str(out.get('content', ''))
        if len(content) > _CONTENT_CAP:
            out['content'] = _cap_at_word(content, _CONTENT_CAP)
        adjusted.append(out)
    adjusted.sort(key=lambda r: r['score'], reverse=True)
    return adjusted[:limit]
