# aingram/cc_hook/client.py
from __future__ import annotations

import http.client
import json
from typing import Any


class DaemonError(Exception):
    """Raised by DaemonClient on any failure path (refused, timeout, 5xx, etc.)."""


class DaemonClient:
    def __init__(self, *, host: str, port: int, timeout_ms: int) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout_ms / 1000.0

    def recall(
        self,
        *,
        query: str,
        limit: int,
        score_threshold: float,
        cwd: str | None,
        seen_entry_ids: list[str],
        project_boost: float,
        seen_demote: float,
    ) -> list[dict[str, Any]]:
        body = json.dumps(
            {
                'query': query,
                'limit': limit,
                'score_threshold': score_threshold,
                'cwd': cwd,
                'seen_entry_ids': seen_entry_ids,
                'project_boost': project_boost,
                'seen_demote': seen_demote,
            }
        ).encode()
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            try:
                conn.request(
                    'POST',
                    '/recall',
                    body=body,
                    headers={
                        'content-type': 'application/json',
                        'content-length': str(len(body)),
                    },
                )
                resp = conn.getresponse()
                data = resp.read()
            except (ConnectionRefusedError, TimeoutError, OSError, http.client.HTTPException) as e:
                raise DaemonError(f'daemon request failed: {e}') from e
            if resp.status < 200 or resp.status >= 300:
                raise DaemonError(f'daemon returned {resp.status}: {data[:200]!r}')
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as e:
                raise DaemonError(f'daemon returned non-JSON: {e}') from e
            results = parsed.get('results')
            if not isinstance(results, list):
                raise DaemonError('daemon response missing results list')
            return results
        finally:
            conn.close()
