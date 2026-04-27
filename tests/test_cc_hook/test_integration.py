# tests/test_cc_hook/test_integration.py
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / 'aingram_cc_hook.py'


@pytest.mark.integration
def test_hook_round_trip_demotes_previously_seen(tmp_path: Path) -> None:
    """Real daemon + real hook script end-to-end.

    Uses a stub MemoryStore via a test-only daemon entrypoint so we don't
    depend on ONNX model downloads.
    """
    from aingram.recall_daemon.server import RecallDaemon
    from tests.test_recall_daemon.test_server import _StubResult, _StubStore

    store = _StubStore(
        [
            _StubResult('first', 0.9, 'first memory content'),
            _StubResult('second', 0.5, 'second memory content'),
        ]
    )
    # port=0 lets the OS assign a free port; read actual port from base_url after start.
    daemon = RecallDaemon(store=store, host='127.0.0.1', port=0, idle_shutdown_seconds=60)
    daemon.start()
    port = int(daemon.base_url.rsplit(':', 1)[-1])
    try:
        env = os.environ.copy()
        env['AINGRAM_HOOK_TIMEOUT_MS'] = '2000'
        # point hook at our ephemeral port via hook.toml
        seen_dir = tmp_path / 'seen'
        hook_toml = tmp_path / 'hook.toml'
        hook_toml.write_text(
            f'daemon_port = {port}\n'
            f'hook_timeout_ms = 2000\n'
            f'[session]\n'
            f'seen_cache_dir = "{seen_dir.as_posix()}"\n',
            encoding='utf-8',
        )
        home = tmp_path / 'home'
        (home / '.aingram').mkdir(parents=True)
        (home / '.aingram' / 'hook.toml').write_text(
            hook_toml.read_text(encoding='utf-8'), encoding='utf-8'
        )
        env['HOME'] = str(home)
        env['USERPROFILE'] = str(home)  # Windows

        payload = json.dumps(
            {
                'hook_event_name': 'UserPromptSubmit',
                'session_id': 'sess-integration',
                'cwd': '/some/cwd',
                'prompt': 'help me refactor something substantial',
            }
        )

        def run_hook() -> str:
            proc = subprocess.run(
                [sys.executable, str(HOOK_SCRIPT)],
                input=payload,
                text=True,
                capture_output=True,
                env=env,
                timeout=10,
            )
            assert proc.returncode == 0, proc.stderr
            return proc.stdout

        out1 = run_hook()
        assert '<aingram-memory>' in out1
        assert 'id="first"' in out1

        out2 = run_hook()
        assert '<aingram-memory>' in out2

        (seen_dir / 'sess-integration.json').write_text(
            json.dumps(['first', 'second']), encoding='utf-8'
        )
        out3 = run_hook()
        assert 'id="first"' in out3
    finally:
        daemon.stop()
