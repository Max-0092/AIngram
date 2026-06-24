# aingram/recall_daemon/server.py
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from aingram.recall_daemon.ranking import apply_ranking
from aingram.security.bounds import sanitize_for_prompt

logger = logging.getLogger(__name__)

_MAX_SEEN_IDS = 500


_CLIENT_DISCONNECT_ERRORS = (ConnectionAbortedError, BrokenPipeError, ConnectionResetError)


class _ReuseThreadingHTTPServer(ThreadingHTTPServer):
    """Avoid Windows ephemeral-port reuse issues between sequential test servers."""

    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Client disconnected before we finished writing (e.g. hook timeout) — benign.
        if issubclass(sys.exc_info()[0], _CLIENT_DISCONNECT_ERRORS):
            logger.debug('client %s disconnected before response was sent', client_address)
            return
        super().handle_error(request, client_address)


class _StoreProto(Protocol):
    def recall(self, query: str, *, limit: int = 20, verify: bool = True) -> list: ...
    def relevance_for(self, query: str, entry_ids: list[str]) -> dict[str, float]: ...
    def close(self) -> None: ...


class RecallDaemon:
    """Loopback HTTP server wrapping MemoryStore.recall() with ranking."""

    def __init__(
        self,
        *,
        store: _StoreProto,
        host: str = '127.0.0.1',
        port: int = 7750,
        idle_shutdown_seconds: float = 30 * 60,
    ) -> None:
        self._store = store
        self._host = host
        self._requested_port = port
        self._idle_shutdown_seconds = idle_shutdown_seconds
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._last_request_at = time.time()
        self._started_at: float | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._store_closed = False

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError('daemon not started')
        port = self._server.server_address[1]
        return f'http://{self._host}:{port}'

    def start(self) -> None:
        daemon_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # silence stderr
                return

            def do_GET(self):  # noqa: N802
                if self.path == '/health':
                    daemon_ref._handle_health(self)
                else:
                    self.send_error(404, 'not found')

            def do_POST(self):  # noqa: N802
                if self.path == '/recall':
                    daemon_ref._handle_recall(self)
                else:
                    self.send_error(404, 'not found')

        # Warm up ONNX before binding the port so the hook never connects to a
        # daemon that can't yet serve requests within hook_timeout_ms.
        self._warmup()

        self._server = _ReuseThreadingHTTPServer((self._host, self._requested_port), Handler)
        self._started_at = time.time()
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _warmup(self) -> None:
        """Compile the ONNX JIT kernel synchronously before the HTTP port is bound."""
        try:
            self._store.recall('warmup', limit=1, verify=False)
            logger.debug('embedder warmed up')
        except Exception:
            pass

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._shutdown_event.set()
        srv = self._server
        self._server = None
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except OSError:
                pass
        if self._server_thread is not None:
            self._server_thread.join(timeout=2)
            self._server_thread = None
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None
        if not self._store_closed:
            self._store.close()
            self._store_closed = True

    def _monitor_loop(self) -> None:
        while not self._shutdown_event.is_set():
            if self._shutdown_event.wait(timeout=1.0):
                return
            with self._lock:
                idle = time.time() - self._last_request_at
            if idle >= self._idle_shutdown_seconds:
                logger.info('idle for %.1fs, shutting down', idle)
                with self._lock:
                    srv = self._server
                    self._server = None
                if srv is not None:
                    try:
                        srv.shutdown()
                    except OSError:
                        pass
                    try:
                        srv.server_close()
                    except OSError:
                        pass
                self._shutdown_event.set()
                return

    def _read_body(self, handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
        try:
            length = int(handler.headers.get('content-length', '0'))
        except ValueError:
            return None
        raw = handler.rfile.read(length) if length > 0 else b''
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _write_json(self, handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        handler.send_response(status)
        handler.send_header('content-type', 'application/json')
        handler.send_header('content-length', str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def _handle_health(self, handler: BaseHTTPRequestHandler) -> None:
        now = time.time()
        with self._lock:
            self._last_request_at = now
        uptime = now - (self._started_at or now)
        self._write_json(
            handler,
            200,
            {
                'ready': True,
                'embedder_loaded': True,
                'uptime_sec': round(uptime, 2),
            },
        )

    def _handle_recall(self, handler: BaseHTTPRequestHandler) -> None:
        body = self._read_body(handler)
        if body is None:
            self._write_json(handler, 400, {'error': 'malformed JSON body'})
            return
        query = body.get('query')
        if not isinstance(query, str) or not query:
            self._write_json(handler, 400, {'error': 'missing or empty "query"'})
            return
        seen = body.get('seen_entry_ids') or []
        if not isinstance(seen, list) or len(seen) > _MAX_SEEN_IDS:
            self._write_json(
                handler,
                400,
                {'error': f'"seen_entry_ids" must be a list of <= {_MAX_SEEN_IDS}'},
            )
            return
        try:
            limit = int(body.get('limit', 8))
            score_threshold = float(body.get('score_threshold', 0.0))
            project_boost = float(body.get('project_boost', 0.0))
            seen_demote = float(body.get('seen_demote', 0.0))
        except (TypeError, ValueError) as e:
            self._write_json(handler, 400, {'error': f'invalid numeric parameter: {e}'})
            return
        cwd = body.get('cwd')

        t0 = time.time()
        with self._lock:
            self._last_request_at = t0
        try:
            raw_results = self._store.recall(query, limit=limit * 3, verify=False)
        except FileNotFoundError as e:
            logger.warning('db missing: %s', e)
            self._write_json(handler, 503, {'error': 'database unavailable'})
            return
        except Exception as e:  # noqa: BLE001
            logger.exception('recall failed')
            self._write_json(handler, 500, {'error': f'recall failed: {e}'})
            return

        # Absolute cosine relevance (0–1) per result — display-only signal so the
        # consumer can judge match strength (RRF score is rank-based, not a relevance
        # reading). Does not affect ranking or the threshold filter below.
        relevance = self._store.relevance_for(
            query, [r.entry.entry_id for r in raw_results]
        )
        raw_dicts = [
            {
                'entry_id': r.entry.entry_id,
                'score': r.score,
                'relevance': relevance.get(r.entry.entry_id),
                'content': r.entry.content,
                'entry_type': str(r.entry.entry_type),
                'created_at': r.entry.created_at,
                'importance': r.entry.importance,
                'project_path': (r.entry.metadata or {}).get('project_path')
                if r.entry.metadata
                else None,
                'trust_score': r.entry.trust_score,
                'status': r.entry.status,
                'role': 'data',
            }
            for r in raw_results
        ]
        ranked = apply_ranking(
            raw_dicts,
            cwd=cwd,
            seen=[str(x) for x in seen],
            project_boost=project_boost,
            seen_demote=seen_demote,
            score_threshold=score_threshold,
            limit=limit,
        )
        for _d in ranked:
            # Sanitize every agent-influenceable field at egress. Ranking has already
            # consumed project_path (apply_ranking above), so mutating it here is safe.
            _d['content'] = sanitize_for_prompt(_d['content'])
            if _d.get('project_path'):
                _d['project_path'] = sanitize_for_prompt(_d['project_path'])
        daemon_ms = round((time.time() - t0) * 1000, 1)
        self._write_json(handler, 200, {'results': ranked, 'daemon_ms': daemon_ms})
