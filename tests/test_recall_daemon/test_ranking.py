# tests/test_recall_daemon/test_ranking.py
from __future__ import annotations

from aingram.recall_daemon.ranking import apply_ranking


def _raw(eid: str, score: float, project_path: str | None = None) -> dict:
    return {
        'entry_id': eid,
        'score': score,
        'content': f'content for {eid}',
        'entry_type': 'observation',
        'created_at': '2026-04-14T10:00:00Z',
        'importance': 0.5,
        'project_path': project_path,
    }


def test_returns_top_n_by_score() -> None:
    raw = [_raw('a', 0.4), _raw('b', 0.7), _raw('c', 0.1)]
    out = apply_ranking(
        raw,
        cwd=None,
        seen=[],
        project_boost=0.0,
        seen_demote=0.0,
        score_threshold=0.0,
        limit=2,
    )
    assert [r['entry_id'] for r in out] == ['b', 'a']


def test_project_boost_applied_for_matching_cwd() -> None:
    raw = [
        _raw('a', 0.40, project_path='/path/to/ProjA'),
        _raw('b', 0.45, project_path='/path/to/ProjB'),
    ]
    out = apply_ranking(
        raw,
        cwd='/path/to/ProjA',
        seen=[],
        project_boost=0.15,
        seen_demote=0.0,
        score_threshold=0.0,
        limit=2,
    )
    # a was 0.40, boosted to 0.55; b stays at 0.45
    assert [r['entry_id'] for r in out] == ['a', 'b']


def test_seen_demote_pushes_seen_entries_down() -> None:
    raw = [_raw('a', 0.50), _raw('b', 0.45)]
    out = apply_ranking(
        raw,
        cwd=None,
        seen=['a'],
        project_boost=0.0,
        seen_demote=0.20,
        score_threshold=0.0,
        limit=2,
    )
    # a = 0.30, b = 0.45
    assert [r['entry_id'] for r in out] == ['b', 'a']


def test_threshold_filters_below_threshold() -> None:
    raw = [_raw('a', 0.40), _raw('b', 0.20), _raw('c', 0.10)]
    out = apply_ranking(
        raw,
        cwd=None,
        seen=[],
        project_boost=0.0,
        seen_demote=0.0,
        score_threshold=0.25,
        limit=10,
    )
    assert [r['entry_id'] for r in out] == ['a']


def test_threshold_applied_after_boost_and_demote() -> None:
    raw = [
        _raw('a', 0.20, project_path='/p/Same'),  # boost +0.15 → 0.35
        _raw('b', 0.30),  # no change
        _raw('c', 0.40),  # demoted by 0.20 → 0.20
    ]
    out = apply_ranking(
        raw,
        cwd='/p/Same',
        seen=['c'],
        project_boost=0.15,
        seen_demote=0.20,
        score_threshold=0.25,
        limit=10,
    )
    assert [r['entry_id'] for r in out] == ['a', 'b']


def test_content_truncated_to_500_chars() -> None:
    long = 'x' * 1000
    raw = [
        {
            'entry_id': 'a',
            'score': 0.5,
            'content': long,
            'entry_type': 'observation',
            'created_at': '2026-04-14T10:00:00Z',
            'importance': 0.5,
            'project_path': None,
        }
    ]
    out = apply_ranking(
        raw,
        cwd=None,
        seen=[],
        project_boost=0.0,
        seen_demote=0.0,
        score_threshold=0.0,
        limit=1,
    )
    assert len(out[0]['content']) == 500


def test_empty_input_returns_empty() -> None:
    out = apply_ranking(
        [],
        cwd=None,
        seen=[],
        project_boost=0.15,
        seen_demote=0.20,
        score_threshold=0.25,
        limit=5,
    )
    assert out == []


def test_limit_respected_after_filter() -> None:
    raw = [_raw(chr(ord('a') + i), 0.9 - 0.01 * i) for i in range(10)]
    out = apply_ranking(
        raw,
        cwd=None,
        seen=[],
        project_boost=0.0,
        seen_demote=0.0,
        score_threshold=0.0,
        limit=3,
    )
    assert len(out) == 3


def _r(entry_id: str, score: float, relevance: float | None) -> dict:
    d = {'entry_id': entry_id, 'score': score, 'content': entry_id}
    if relevance is not None:
        d['relevance'] = relevance
    return d


def _rank(results, **kw):
    base = dict(
        cwd=None, seen=[], project_boost=0.0, seen_demote=0.0,
        score_threshold=0.0, limit=10,
    )
    base.update(kw)
    return apply_ranking(results, **base)


def test_relevance_threshold_drops_weak_matches() -> None:
    out = _rank(
        [_r('hit', 0.004, 0.63), _r('tangential', 0.004, 0.43)],
        relevance_threshold=0.45,
    )
    assert [r['entry_id'] for r in out] == ['hit']


def test_relevance_threshold_defaults_to_off() -> None:
    """Existing deployments must keep their behaviour when the knob is unset."""
    out = _rank([_r('a', 0.004, 0.10), _r('b', 0.004, 0.05)])
    assert len(out) == 2


def test_missing_relevance_is_never_dropped() -> None:
    """A store that cannot compute cosine must not silently return nothing."""
    out = _rank([_r('no_rel', 0.004, None)], relevance_threshold=0.9)
    assert [r['entry_id'] for r in out] == ['no_rel']


def test_relevance_and_score_thresholds_are_independent() -> None:
    out = _rank(
        [_r('low_score_high_rel', 0.001, 0.9), _r('high_score_low_rel', 0.05, 0.1)],
        score_threshold=0.01,
        relevance_threshold=0.5,
    )
    assert out == []
