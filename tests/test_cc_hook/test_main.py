# tests/test_cc_hook/test_main.py
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aingram.cc_hook.config import HookConfig
from aingram.cc_hook.main import run


def _make_cfg(tmp_path: Path, **overrides) -> HookConfig:
    cfg = HookConfig(seen_cache_dir=str(tmp_path / 'seen'))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _run_with(payload: dict, cfg: HookConfig, client_mock) -> tuple[str, int]:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client_mock):
        exit_code = run(stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: None)
    return stdout.getvalue(), exit_code


def test_user_prompt_submit_emits_memory_block(tmp_path: Path) -> None:
    client = MagicMock()
    client.recall.return_value = [
        {
            'entry_id': 'a',
            'score': 0.5,
            'content': 'alpha',
            'entry_type': 'lesson',
            'created_at': '2026-04-14T10:00:00Z',
        },
    ]
    cfg = _make_cfg(tmp_path)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 'sess-1',
        'cwd': '/p/ProjA',
        'prompt': 'refactor the drain logic',
    }
    out, code = _run_with(payload, cfg, client)
    assert code == 0
    assert '<aingram-memory>' in out
    assert 'id="a"' in out
    client.recall.assert_called_once()


def test_pre_tool_use_edit_emits_memory_block(tmp_path: Path) -> None:
    client = MagicMock()
    client.recall.return_value = [
        {
            'entry_id': 'b',
            'score': 0.4,
            'content': 'beta',
            'entry_type': 'decision',
            'created_at': '2026-04-14T10:00:00Z',
        },
    ]
    cfg = _make_cfg(tmp_path)
    payload = {
        'hook_event_name': 'PreToolUse',
        'session_id': 'sess-1',
        'cwd': '/p/ProjA',
        'tool_name': 'Edit',
        'tool_input': {
            'file_path': 'foo.py',
            'old_string': 'def old_function():',
            'new_string': 'def new_function():',
        },
    }
    out, code = _run_with(payload, cfg, client)
    assert code == 0
    assert 'id="b"' in out


def test_disabled_config_skips_daemon_call(tmp_path: Path) -> None:
    client = MagicMock()
    cfg = _make_cfg(tmp_path, enabled=False)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's',
        'cwd': '/p',
        'prompt': 'anything long enough here',
    }
    out, code = _run_with(payload, cfg, client)
    assert code == 0
    assert out == ''
    client.recall.assert_not_called()


def test_empty_query_skips_daemon_call(tmp_path: Path) -> None:
    client = MagicMock()
    cfg = _make_cfg(tmp_path)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's',
        'cwd': '/p',
        'prompt': 'hi',
    }
    out, code = _run_with(payload, cfg, client)
    assert code == 0
    assert out == ''
    client.recall.assert_not_called()


def test_daemon_error_exits_zero_empty_stdout(tmp_path: Path) -> None:
    from aingram.cc_hook.client import DaemonError

    client = MagicMock()
    client.recall.side_effect = DaemonError('refused')
    cfg = _make_cfg(tmp_path)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's',
        'cwd': '/p',
        'prompt': 'a long enough prompt here',
    }
    spawn_called = []

    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        code = run(
            stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: spawn_called.append(True)
        )
    assert code == 0
    assert stdout.getvalue() == ''
    assert spawn_called == [True]


def test_daemon_timeout_error_spawns_daemon(tmp_path: Path) -> None:
    # On Windows, a closed port takes ~2s to return ECONNREFUSED, so Python's
    # socket timeout fires first (TimeoutError). Timeout must trigger a spawn
    # just like ConnectionRefusedError does.
    from aingram.cc_hook.client import DaemonError

    client = MagicMock()
    client.recall.side_effect = DaemonError('daemon request failed: timed out')
    cfg = _make_cfg(tmp_path)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's',
        'cwd': '/p',
        'prompt': 'a long enough prompt here',
    }
    spawn_called = []

    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        code = run(
            stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: spawn_called.append(True)
        )
    assert code == 0
    assert stdout.getvalue() == ''
    assert spawn_called == [True]


def test_malformed_stdin_exits_zero_empty(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    stdin = io.StringIO('not json')
    stdout = io.StringIO()
    code = run(stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: None)
    assert code == 0
    assert stdout.getvalue() == ''


def test_seen_ids_sent_and_appended(tmp_path: Path) -> None:
    client = MagicMock()
    client.recall.return_value = [
        {
            'entry_id': 'new1',
            'score': 0.5,
            'content': 'x',
            'entry_type': 'observation',
            'created_at': '2026-04-14T10:00:00Z',
        },
    ]
    cfg = _make_cfg(tmp_path)
    # prime the seen store
    (tmp_path / 'seen').mkdir()
    (tmp_path / 'seen' / 'sess-1.json').write_text(json.dumps(['prev']), encoding='utf-8')

    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 'sess-1',
        'cwd': '/p',
        'prompt': 'a long enough prompt here',
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        run(stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: None)

    _, kwargs = client.recall.call_args
    assert kwargs['seen_entry_ids'] == ['prev']

    updated = json.loads((tmp_path / 'seen' / 'sess-1.json').read_text())
    assert updated == ['prev', 'new1']


def test_main_handles_non_cp1252_output_on_piped_stdout(tmp_path: Path, monkeypatch) -> None:
    """Regression: Windows piped-child stdout defaults to cp1252. Recall entries
    routinely contain chars outside cp1252 (emoji, CJK, box-drawing, math symbols).
    Before the fix, stdout.write raised UnicodeEncodeError → uncaught traceback →
    non-zero exit → Claude Code showed 'non-blocking status code: Traceback'.
    """
    import io
    import sys

    import aingram.cc_hook.main as hook_main

    stdout_bytes = io.BytesIO()
    fake_stdout = io.TextIOWrapper(
        stdout_bytes, encoding='cp1252', errors='strict', write_through=True
    )
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's1',
        'cwd': '/p',
        'prompt': 'a long enough prompt here for derive_query',
    }
    fake_stdin = io.StringIO(json.dumps(payload))
    client = MagicMock()
    client.recall.return_value = [
        {
            'entry_id': 'a',
            'score': 0.5,
            'content': 'emoji: 🚀 CJK: 你好 math: ⊕',  # none representable in cp1252
            'entry_type': 'lesson',
            'created_at': '2026-04-14T10:00:00Z',
        }
    ]
    monkeypatch.setattr(sys, 'stdin', fake_stdin)
    monkeypatch.setattr(sys, 'stdout', fake_stdout)
    monkeypatch.setattr(
        hook_main,
        'load_hook_config',
        lambda env: HookConfig(seen_cache_dir=str(tmp_path / 'seen')),
    )

    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        with pytest.raises(SystemExit) as exc_info:
            hook_main.main()

    assert exc_info.value.code == 0
    fake_stdout.flush()
    decoded = stdout_bytes.getvalue().decode('utf-8', errors='replace')
    assert '<aingram-memory>' in decoded
    # non-cp1252 glyphs should survive (fix reconfigures to utf-8 before write)
    assert '🚀' in decoded
    assert '你好' in decoded


def test_main_swallows_unhandled_exceptions_and_exits_zero(tmp_path: Path, monkeypatch) -> None:
    """Defense-in-depth: any uncaught exception in run() must not surface to
    Claude Code as a traceback. Log it, exit 0."""
    import io
    import sys

    import aingram.cc_hook.main as hook_main

    monkeypatch.setattr(sys, 'stdin', io.StringIO('{}'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(hook_main, 'load_hook_config', lambda env: HookConfig())

    def boom(**_kwargs):
        raise RuntimeError('simulated bug deep in hook')

    monkeypatch.setattr(hook_main, 'run', boom)

    with pytest.raises(SystemExit) as exc_info:
        hook_main.main()
    assert exc_info.value.code == 0


def test_prompt_event_uses_prompt_budget(tmp_path: Path) -> None:
    client = MagicMock()
    client.recall.return_value = []
    cfg = _make_cfg(tmp_path, prompt_limit=7, prompt_score_threshold=0.11)
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'session_id': 's',
        'cwd': '/p',
        'prompt': 'long enough query string',
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        run(stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: None)
    _, kwargs = client.recall.call_args
    assert kwargs['limit'] == 7
    assert kwargs['score_threshold'] == pytest.approx(0.11)


def test_edit_event_uses_edit_budget(tmp_path: Path) -> None:
    client = MagicMock()
    client.recall.return_value = []
    cfg = _make_cfg(tmp_path, edit_limit=2, edit_score_threshold=0.33)
    payload = {
        'hook_event_name': 'PreToolUse',
        'session_id': 's',
        'cwd': '/p',
        'tool_name': 'Edit',
        'tool_input': {'file_path': 'x.py', 'old_string': 'old', 'new_string': 'new'},
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch('aingram.cc_hook.main.DaemonClient', return_value=client):
        run(stdin=stdin, stdout=stdout, cfg=cfg, spawn_daemon=lambda: None)
    _, kwargs = client.recall.call_args
    assert kwargs['limit'] == 2
    assert kwargs['score_threshold'] == pytest.approx(0.33)
