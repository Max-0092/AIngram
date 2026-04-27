# aingram/cc_hook/seen.py
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_SESSION_ID = re.compile(r'[^A-Za-z0-9_-]')


def _sanitize(session_id: str) -> str:
    return _SAFE_SESSION_ID.sub('_', session_id) or 'default'


class SeenStore:
    """Per-session set of entry_ids the hook has already surfaced.

    Files live at <cache_dir>/<sanitized-session-id>.json and contain a JSON
    array of entry_id strings. Writes are atomic via temp-file + rename.
    """

    def __init__(self, *, cache_dir: Path, cap: int) -> None:
        self._cache_dir = Path(cache_dir).expanduser()
        self._cap = cap

    def _path(self, session_id: str) -> Path:
        return self._cache_dir / f'{_sanitize(session_id)}.json'

    def read(self, session_id: str) -> list[str]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('seen file unreadable, treating as empty: %s', e)
            return []
        if not isinstance(data, list):
            return []
        return [str(x) for x in data]

    def write(self, session_id: str, entry_ids: list[str]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        capped = entry_ids[-self._cap :] if len(entry_ids) > self._cap else entry_ids
        path = self._path(session_id)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(capped), encoding='utf-8')
        os.replace(tmp, path)

    def append(self, session_id: str, new_ids: list[str]) -> None:
        existing = self.read(session_id)
        seen: set[str] = set(existing)
        merged = list(existing)
        for eid in new_ids:
            if eid not in seen:
                merged.append(eid)
                seen.add(eid)
        self.write(session_id, merged)

    def cleanup_stale(self, *, stale_days: int) -> int:
        if not self._cache_dir.exists():
            return 0
        cutoff = time.time() - stale_days * 86400
        removed = 0
        for p in self._cache_dir.glob('*.json'):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError as e:
                logger.warning('could not remove stale seen file %s: %s', p, e)
        return removed
