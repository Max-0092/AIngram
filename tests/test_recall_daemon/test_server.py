# tests/test_recall_daemon/test_server.py
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError

import pytest

from aingram.recall_daemon.server import RecallDaemon


@dataclass
class _StubResult:
    entry_id: str
    score: float
    content: str
    entry_type: str = 'observation'
    created_at: str = '2026-04-14T10:00:00Z'
    importance: float = 0.5
    project_path: str | None = None


class _StubStore:
    def __init__(self, results: list[_StubResult]) -> None:
        self._results = results
        self.last_query: str | None = None
        self.last_limit: int | None = None

    def recall(self, query: str, *, limit: int = 20, verify: bool = True) -> list:
        self.last_query = query
        self.last_limit = limit

        class _Entry:
            def __init__(self, r: _StubResult):
                self.entry_id = r.entry_id
                self.content = r.content
                self.entry_type = r.entry_type
                self.created_at = r.created_at
                self.importance = r.importance
                self.metadata = {'project_path': r.project_path} if r.project_path else None
                self.trust_score = None
                self.status = 'pending'

        class _Wrapped:
            def __init__(self, r: _StubResult):
                self.entry = _Entry(r)
                self.score = r.score

        return [_Wrapped(r) for r in self._results]

    def relevance_for(self, query: str, entry_ids: list[str]) -> dict[str, float]:
        return {eid: 0.5 for eid in entry_ids}

    def close(self) -> None:
        pass


@pytest.fixture
def daemon(tmp_path: Path):
    store = _StubStore(
        [
            _StubResult('a', 0.5, 'alpha', project_path='/p/ProjA'),
            _StubResult('b', 0.4, 'beta', project_path='/p/ProjB'),
            _StubResult('c', 0.2, 'gamma'),
        ]
    )
    d = RecallDaemon(
        store=store,
        host='127.0.0.1',
        port=0,  # let OS pick
        idle_shutdown_seconds=60,
    )
    d.start()
    yield d
    d.stop()


def _post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={'content-type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_returns_ready_with_stats(daemon: RecallDaemon) -> None:
    with urllib.request.urlopen(f'{daemon.base_url}/health', timeout=2) as resp:
        assert resp.status == 200
        body = json.loads(resp.read())
        assert body['ready'] is True


def test_recall_returns_ranked_results(daemon: RecallDaemon) -> None:
    status, body = _post(
        f'{daemon.base_url}/recall',
        {
            'query': 'hello world',
            'limit': 2,
            'score_threshold': 0.0,
            'cwd': None,
            'seen_entry_ids': [],
            'project_boost': 0.0,
            'seen_demote': 0.0,
        },
    )
    assert status == 200
    assert len(body['results']) == 2
    assert body['results'][0]['entry_id'] == 'a'
    assert 'daemon_ms' in body


def test_recall_applies_project_boost(daemon: RecallDaemon) -> None:
    status, body = _post(
        f'{daemon.base_url}/recall',
        {
            'query': 'hello world',
            'limit': 3,
            'score_threshold': 0.0,
            'cwd': '/p/ProjB',
            'seen_entry_ids': [],
            'project_boost': 0.20,
            'seen_demote': 0.0,
        },
    )
    # b was 0.4 → 0.6 with boost; a was 0.5
    assert status == 200
    assert body['results'][0]['entry_id'] == 'b'


def test_recall_rejects_malformed_json(daemon: RecallDaemon) -> None:
    req = urllib.request.Request(
        f'{daemon.base_url}/recall',
        data=b'not json',
        headers={'content-type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=2)
        pytest.fail('expected HTTPError')
    except HTTPError as e:
        assert e.code == 400


def test_recall_rejects_missing_query(daemon: RecallDaemon) -> None:
    status, body = _post(f'{daemon.base_url}/recall', {'limit': 5})
    assert status == 400
    assert 'query' in body.get('error', '').lower()


def test_recall_rejects_oversized_seen_list(daemon: RecallDaemon) -> None:
    status, body = _post(
        f'{daemon.base_url}/recall',
        {
            'query': 'x' * 20,
            'seen_entry_ids': ['id'] * 501,
        },
    )
    assert status == 400


def test_unknown_path_returns_404(daemon: RecallDaemon) -> None:
    req = urllib.request.Request(f'{daemon.base_url}/bogus', method='GET')
    try:
        urllib.request.urlopen(req, timeout=2)
        pytest.fail('expected HTTPError')
    except HTTPError as e:
        assert e.code == 404


def test_handle_error_suppresses_client_disconnect_errors(daemon: RecallDaemon) -> None:
    import io
    import sys

    srv = daemon._server
    assert srv is not None

    for exc_cls in (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
        captured = io.StringIO()
        try:
            raise exc_cls('simulated client abort')
        except exc_cls:
            old_stderr, sys.stderr = sys.stderr, captured
            try:
                srv.handle_error(None, ('127.0.0.1', 0))
            finally:
                sys.stderr = old_stderr
        assert exc_cls.__name__ not in captured.getvalue(), (
            f'{exc_cls.__name__} should be silently swallowed by handle_error'
        )


def test_recall_rejects_malformed_numeric_params(daemon: RecallDaemon) -> None:
    status, body = _post(
        f'{daemon.base_url}/recall',
        {'query': 'hello world', 'limit': 'not-a-number'},
    )
    assert status == 400
    assert 'invalid numeric' in body.get('error', '').lower()
