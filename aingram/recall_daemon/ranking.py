# aingram/recall_daemon/ranking.py
from __future__ import annotations

from typing import Any

_CONTENT_CAP = 500


def apply_ranking(
    results: list[dict[str, Any]],
    *,
    cwd: str | None,
    seen: list[str],
    project_boost: float,
    seen_demote: float,
    score_threshold: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Project-boost + seen-demote + threshold filter, in Python (never SQL).

    Input results carry 'entry_id', 'score', 'project_path', etc.
    Returns a new list of dicts with adjusted scores, sorted desc, truncated
    to `limit`, with content capped at 500 chars.
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
        out = dict(r)
        out['score'] = score
        content = str(out.get('content', ''))
        if len(content) > _CONTENT_CAP:
            out['content'] = content[:_CONTENT_CAP]
        adjusted.append(out)
    adjusted.sort(key=lambda r: r['score'], reverse=True)
    return adjusted[:limit]
