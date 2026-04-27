# tests/test_cc_hook/test_install.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aingram.cc_hook.install import _SENTINEL_KEY, install_hooks, uninstall_hooks


def test_install_creates_settings_with_our_entries(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    hook_path = tmp_path / 'aingram_cc_hook.py'
    hook_path.write_text('')
    result = install_hooks(settings_path=settings, hook_script=hook_path)
    assert result.installed is True
    data = json.loads(settings.read_text())
    assert 'hooks' in data
    assert 'UserPromptSubmit' in data['hooks']
    assert 'PreToolUse' in data['hooks']
    matcher_groups = data['hooks']['PreToolUse']
    assert any('Edit|Write|NotebookEdit' in mg.get('matcher', '') for mg in matcher_groups)


def test_install_preserves_existing_non_aingram_hooks(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    existing = {
        'hooks': {
            'UserPromptSubmit': [
                {'hooks': [{'type': 'command', 'command': '/custom/hook.sh'}]},
            ],
            'Stop': [{'hooks': [{'type': 'command', 'command': '/my/stop.sh'}]}],
        },
        'unrelated': 'value',
    }
    settings.write_text(json.dumps(existing))
    hook_path = tmp_path / 'aingram_cc_hook.py'
    hook_path.write_text('')
    install_hooks(settings_path=settings, hook_script=hook_path)
    data = json.loads(settings.read_text())
    assert data['unrelated'] == 'value'
    # custom hook survives
    custom = [
        mg
        for mg in data['hooks']['UserPromptSubmit']
        if any(h.get('command') == '/custom/hook.sh' for h in mg.get('hooks', []))
    ]
    assert len(custom) == 1
    # aingram hook also present
    aingram = [
        mg
        for mg in data['hooks']['UserPromptSubmit']
        if any(_SENTINEL_KEY in str(h) for h in mg.get('hooks', []))
    ]
    assert len(aingram) == 1
    # Stop event untouched
    assert data['hooks']['Stop'] == existing['hooks']['Stop']


def test_install_is_idempotent(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    hook_path = tmp_path / 'aingram_cc_hook.py'
    hook_path.write_text('')
    install_hooks(settings_path=settings, hook_script=hook_path)
    data1 = json.loads(settings.read_text())
    result2 = install_hooks(settings_path=settings, hook_script=hook_path)
    data2 = json.loads(settings.read_text())
    assert result2.installed is False  # already present
    assert data1 == data2


def test_uninstall_removes_only_aingram_entries(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    hook_path = tmp_path / 'aingram_cc_hook.py'
    hook_path.write_text('')
    # existing custom + install aingram
    existing = {
        'hooks': {
            'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': '/custom/hook.sh'}]}]
        }
    }
    settings.write_text(json.dumps(existing))
    install_hooks(settings_path=settings, hook_script=hook_path)
    uninstall_hooks(settings_path=settings)
    data = json.loads(settings.read_text())
    # custom survives
    assert any(
        h.get('command') == '/custom/hook.sh'
        for mg in data['hooks']['UserPromptSubmit']
        for h in mg.get('hooks', [])
    )
    # no aingram entries anywhere
    flat = json.dumps(data)
    assert _SENTINEL_KEY not in flat


def test_uninstall_on_missing_file_is_noop(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'  # does not exist
    result = uninstall_hooks(settings_path=settings)
    assert result.removed is False
    assert not settings.exists()


def test_install_command_uses_sys_executable_quoted(tmp_path: Path) -> None:
    import sys

    settings = tmp_path / 'settings.json'
    hook_path = tmp_path / 'my hook script.py'
    hook_path.write_text('')
    install_hooks(settings_path=settings, hook_script=hook_path)
    data = json.loads(settings.read_text())
    all_commands = [
        h.get('command', '')
        for event in data.get('hooks', {}).values()
        for mg in event
        for h in mg.get('hooks', [])
    ]
    for cmd in all_commands:
        assert f'"{sys.executable}"' in cmd, f'sys.executable not quoted in: {cmd}'
        assert f'"{hook_path}"' in cmd, f'hook_script not quoted in: {cmd}'


def test_install_custom_tool_matchers(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    hook_path = tmp_path / 'hook.py'
    hook_path.write_text('')
    install_hooks(settings_path=settings, hook_script=hook_path, tool_matchers=['Edit', 'Bash'])
    data = json.loads(settings.read_text())
    matcher_groups = data['hooks']['PreToolUse']
    assert any('Edit|Bash' == mg.get('matcher') for mg in matcher_groups)


def test_malformed_settings_raises(tmp_path: Path) -> None:
    settings = tmp_path / 'settings.json'
    settings.write_text('not json')
    hook_path = tmp_path / 'aingram_cc_hook.py'
    hook_path.write_text('')

    with pytest.raises(ValueError):
        install_hooks(settings_path=settings, hook_script=hook_path)
