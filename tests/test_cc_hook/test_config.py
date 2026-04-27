# tests/test_cc_hook/test_config.py
from __future__ import annotations

from pathlib import Path

import pytest

from aingram.cc_hook.config import load_hook_config


def test_defaults_when_no_file_and_no_env(tmp_path: Path) -> None:
    cfg = load_hook_config(toml_path=tmp_path / 'missing.toml', env={})
    assert cfg.enabled is True
    assert cfg.daemon_host == '127.0.0.1'
    assert cfg.daemon_port == 7750
    assert cfg.hook_timeout_ms == 2000
    assert cfg.prompt_limit == 8
    assert cfg.prompt_score_threshold == 0.005
    assert cfg.edit_limit == 3
    assert cfg.edit_score_threshold == 0.007
    assert cfg.tool_matchers == ['Edit', 'Write', 'NotebookEdit']
    assert cfg.project_boost == 0.003
    assert cfg.seen_demote == 0.004
    assert cfg.seen_cap == 200
    assert cfg.stale_days == 7
    assert cfg.idle_shutdown_seconds == 30 * 60


def test_toml_overrides_defaults(tmp_path: Path) -> None:
    toml = tmp_path / 'hook.toml'
    toml.write_text(
        'enabled = false\n'
        'daemon_port = 9999\n'
        'hook_timeout_ms = 750\n'
        '[triggers.user_prompt_submit]\n'
        'limit = 12\n'
        'score_threshold = 0.10\n'
        '[scoring]\n'
        'project_boost = 0.25\n',
        encoding='utf-8',
    )
    cfg = load_hook_config(toml_path=toml, env={})
    assert cfg.enabled is False
    assert cfg.daemon_port == 9999
    assert cfg.hook_timeout_ms == 750
    assert cfg.prompt_limit == 12
    assert cfg.prompt_score_threshold == 0.10
    assert cfg.project_boost == 0.25
    assert cfg.edit_limit == 3  # still default


def test_env_overrides_toml(tmp_path: Path) -> None:
    toml = tmp_path / 'hook.toml'
    toml.write_text('daemon_port = 9999\n', encoding='utf-8')
    env = {
        'AINGRAM_HOOK_DISABLED': '1',
        'AINGRAM_HOOK_PROMPT_LIMIT': '20',
        'AINGRAM_HOOK_EDIT_LIMIT': '1',
        'AINGRAM_HOOK_PROJECT_BOOST': '0.30',
        'AINGRAM_HOOK_TIMEOUT_MS': '250',
    }
    cfg = load_hook_config(toml_path=toml, env=env)
    assert cfg.enabled is False
    assert cfg.daemon_port == 9999  # from toml, untouched by env
    assert cfg.prompt_limit == 20
    assert cfg.edit_limit == 1
    assert cfg.project_boost == 0.30
    assert cfg.hook_timeout_ms == 250


def test_env_disabled_flag_accepts_multiple_truthy_values(tmp_path: Path) -> None:
    for v in ('1', 'true', 'yes', 'on', 'TRUE', 'YES'):
        cfg = load_hook_config(
            toml_path=tmp_path / 'missing.toml',
            env={'AINGRAM_HOOK_DISABLED': v},
        )
        assert cfg.enabled is False, v


def test_env_disabled_flag_ignores_falsy_values(tmp_path: Path) -> None:
    for v in ('0', 'false', 'no', '', 'off'):
        cfg = load_hook_config(
            toml_path=tmp_path / 'missing.toml',
            env={'AINGRAM_HOOK_DISABLED': v},
        )
        assert cfg.enabled is True, v


def test_idle_shutdown_minutes_converts_to_seconds(tmp_path: Path) -> None:
    toml = tmp_path / 'hook.toml'
    toml.write_text('idle_shutdown_minutes = 10\n', encoding='utf-8')
    cfg = load_hook_config(toml_path=toml, env={})
    assert cfg.idle_shutdown_seconds == pytest.approx(600.0)


def test_malformed_toml_falls_back_to_defaults(tmp_path: Path) -> None:
    toml = tmp_path / 'hook.toml'
    toml.write_text('this is !! not !! toml\n', encoding='utf-8')
    cfg = load_hook_config(toml_path=toml, env={})
    assert cfg.daemon_port == 7750  # default
