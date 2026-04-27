# tests/test_recall_daemon/test_lifecycle.py
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from aingram.recall_daemon.server import RecallDaemon


class _RaisingStore:
    def recall(self, query, *, limit=20, verify=True):
        raise FileNotFoundError('db gone')

    def close(self):
        pass


class _MinimalStore:
    def recall(self, query, *, limit=20, verify=True):
        return []

    def close(self):
        pass


def test_recall_returns_503_when_db_missing() -> None:
    d = RecallDaemon(
        store=_RaisingStore(),
        host='127.0.0.1',
        port=0,
        idle_shutdown_seconds=60,
    )
    d.start()
    req = urllib.request.Request(
        f'{d.base_url}/recall',
        data=json.dumps({'query': 'anything here'}).encode(),
        headers={'content-type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=2)
        pytest.fail('expected HTTPError')
    except urllib.error.HTTPError as e:
        assert e.code == 503
    d.stop()


def test_stop_is_idempotent() -> None:
    d = RecallDaemon(
        store=_MinimalStore(),
        host='127.0.0.1',
        port=0,
        idle_shutdown_seconds=60,
    )
    d.start()
    d.stop()
    d.stop()  # should not raise


def test_pid_file_is_written_and_removed(tmp_path) -> None:
    from aingram.recall_daemon.cli import PidFile

    pid_path = tmp_path / 'daemon.pid'
    pf = PidFile(pid_path)
    pf.write(os.getpid())
    assert pid_path.exists()
    assert pf.read() == os.getpid()
    pf.remove()
    assert not pid_path.exists()


def test_pid_file_read_missing_returns_none(tmp_path) -> None:
    from aingram.recall_daemon.cli import PidFile

    pf = PidFile(tmp_path / 'nope.pid')
    assert pf.read() is None


def test_pid_file_stale_detection(tmp_path) -> None:
    from aingram.recall_daemon.cli import PidFile

    pf = PidFile(tmp_path / 'daemon.pid')
    pf.write(999999999)  # almost certainly not running
    assert pf.is_stale() is True
    # Use a child process: os.kill(current_pid, 0) on Windows can disrupt later
    # ThreadingHTTPServer-based tests in the same pytest session.
    proc = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(3600)'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        pf.write(proc.pid)
        assert pf.is_stale() is False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_idle_shutdown_exits_cleanly() -> None:
    d = RecallDaemon(
        store=_MinimalStore(),
        host='127.0.0.1',
        port=0,
        idle_shutdown_seconds=0.5,
    )
    d.start()
    # first request resets the timer
    with urllib.request.urlopen(f'{d.base_url}/health', timeout=2) as resp:
        assert resp.status == 200
    time.sleep(2.0)
    # after idle, server should have shut down on its own
    assert d._shutdown_event.is_set()
    d.stop()
