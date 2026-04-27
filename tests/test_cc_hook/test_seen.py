# tests/test_cc_hook/test_seen.py
from __future__ import annotations

import json
import time
from pathlib import Path

from aingram.cc_hook.seen import SeenStore


def test_empty_on_first_read(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    assert store.read('sess-1') == []


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    store.write('sess-1', ['a', 'b', 'c'])
    assert store.read('sess-1') == ['a', 'b', 'c']


def test_cap_applies_with_fifo_eviction(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=3)
    store.write('sess-1', ['a', 'b', 'c', 'd', 'e'])
    assert store.read('sess-1') == ['c', 'd', 'e']


def test_append_preserves_order_and_dedupes(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    store.write('sess-1', ['a', 'b'])
    store.append('sess-1', ['b', 'c', 'a', 'd'])
    assert store.read('sess-1') == ['a', 'b', 'c', 'd']


def test_append_to_empty_creates_file(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    store.append('sess-1', ['a', 'b'])
    assert (tmp_path / 'sess-1.json').exists()
    assert store.read('sess-1') == ['a', 'b']


def test_corrupted_file_treated_as_empty(tmp_path: Path) -> None:
    (tmp_path / 'sess-1.json').write_text('not json', encoding='utf-8')
    store = SeenStore(cache_dir=tmp_path, cap=200)
    assert store.read('sess-1') == []


def test_cleanup_stale_removes_old_files(tmp_path: Path) -> None:
    import os

    fresh = tmp_path / 'fresh.json'
    stale = tmp_path / 'stale.json'
    fresh.write_text(json.dumps(['x']), encoding='utf-8')
    stale.write_text(json.dumps(['y']), encoding='utf-8')
    old = time.time() - 60 * 60 * 24 * 10

    os.utime(stale, (old, old))
    store = SeenStore(cache_dir=tmp_path, cap=200)
    removed = store.cleanup_stale(stale_days=7)
    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_cleanup_handles_missing_dir(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path / 'does-not-exist', cap=200)
    assert store.cleanup_stale(stale_days=7) == 0


def test_write_uses_atomic_rename(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    store.write('sess-1', ['a'])
    assert (tmp_path / 'sess-1.json').exists()
    assert not list(tmp_path.glob('*.tmp'))


def test_session_id_is_sanitized(tmp_path: Path) -> None:
    store = SeenStore(cache_dir=tmp_path, cap=200)
    store.write('evil/../../etc', ['x'])
    written = list(tmp_path.glob('*.json'))
    assert len(written) == 1
    assert '/' not in written[0].name
    assert '..' not in written[0].name
