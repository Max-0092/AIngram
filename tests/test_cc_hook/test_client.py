# tests/test_cc_hook/test_client.py
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aingram.cc_hook.client import DaemonClient, DaemonError


def _make_server(handler_fn):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_POST(self):  # noqa: N802
            handler_fn(self)

    server = ThreadingHTTPServer(('127.0.0.1', 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_successful_recall_returns_results() -> None:
    def handler(h):
        length = int(h.headers.get('content-length', 0))
        body = json.loads(h.rfile.read(length))
        assert body['query'] == 'hello world'
        payload = json.dumps({'results': [{'entry_id': 'a'}], 'daemon_ms': 12}).encode()
        h.send_response(200)
        h.send_header('content-type', 'application/json')
        h.send_header('content-length', str(len(payload)))
        h.end_headers()
        h.wfile.write(payload)

    server, thread = _make_server(handler)
    try:
        port = server.server_address[1]
        client = DaemonClient(host='127.0.0.1', port=port, timeout_ms=2000)
        results = client.recall(
            query='hello world',
            limit=5,
            score_threshold=0.25,
            cwd=None,
            seen_entry_ids=[],
            project_boost=0.15,
            seen_demote=0.20,
        )
        assert results == [{'entry_id': 'a'}]
    finally:
        server.shutdown()
        server.server_close()


def test_connection_refused_raises_daemon_error() -> None:
    # bind to an ephemeral port and close it so the port is known-dead
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    client = DaemonClient(host='127.0.0.1', port=port, timeout_ms=500)
    with pytest.raises(DaemonError) as excinfo:
        client.recall(
            query='hello world',
            limit=5,
            score_threshold=0.0,
            cwd=None,
            seen_entry_ids=[],
            project_boost=0.0,
            seen_demote=0.0,
        )
    msg = str(excinfo.value).lower()
    assert 'refused' in msg or 'connect' in msg or 'timed out' in msg


def test_timeout_raises_daemon_error() -> None:
    def handler(h):
        time.sleep(2)  # exceeds client timeout

    server, thread = _make_server(handler)
    try:
        port = server.server_address[1]
        client = DaemonClient(host='127.0.0.1', port=port, timeout_ms=200)
        with pytest.raises(DaemonError) as excinfo:
            client.recall(
                query='hello world',
                limit=5,
                score_threshold=0.0,
                cwd=None,
                seen_entry_ids=[],
                project_boost=0.0,
                seen_demote=0.0,
            )
        msg = str(excinfo.value).lower()
        assert 'timeout' in msg or 'timed out' in msg
    finally:
        server.shutdown()
        server.server_close()


def test_non_2xx_raises_daemon_error() -> None:
    def handler(h):
        h.send_response(500)
        h.send_header('content-length', '11')
        h.end_headers()
        h.wfile.write(b'server boom')

    server, thread = _make_server(handler)
    try:
        port = server.server_address[1]
        client = DaemonClient(host='127.0.0.1', port=port, timeout_ms=2000)
        with pytest.raises(DaemonError):
            client.recall(
                query='hello world',
                limit=5,
                score_threshold=0.0,
                cwd=None,
                seen_entry_ids=[],
                project_boost=0.0,
                seen_demote=0.0,
            )
    finally:
        server.shutdown()
        server.server_close()
