# aingram/cc_hook/install.py
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_SENTINEL_KEY = 'aingram_cc_hook'
_DEFAULT_MATCHERS = ['Edit', 'Write', 'NotebookEdit']


@dataclass
class InstallResult:
    installed: bool


@dataclass
class UninstallResult:
    removed: bool


def _aingram_group(hook_script: Path) -> dict:
    return {
        _SENTINEL_KEY: True,
        'hooks': [
            {
                'type': 'command',
                'command': f'"{sys.executable}" "{hook_script}"',
                _SENTINEL_KEY: True,
            }
        ],
    }


def _matcher_group(hook_script: Path, tool_matchers: list[str]) -> dict:
    return {
        _SENTINEL_KEY: True,
        'matcher': '|'.join(tool_matchers),
        'hooks': [
            {
                'type': 'command',
                'command': f'"{sys.executable}" "{hook_script}"',
                _SENTINEL_KEY: True,
            }
        ],
    }


def _contains_aingram_entry(groups: list[dict]) -> bool:
    for mg in groups:
        if isinstance(mg, dict) and mg.get(_SENTINEL_KEY):
            return True
    return False


def _strip_aingram_entries(groups: list[dict]) -> list[dict]:
    return [mg for mg in groups if not (isinstance(mg, dict) and mg.get(_SENTINEL_KEY))]


def install_hooks(
    *, settings_path: Path, hook_script: Path, tool_matchers: list[str] | None = None
) -> InstallResult:
    if tool_matchers is None:
        tool_matchers = _DEFAULT_MATCHERS
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            raise ValueError(f'{settings_path} is not valid JSON: {e}') from e
        if not isinstance(data, dict):
            raise ValueError(f'{settings_path} root must be an object')
    else:
        data = {}

    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('settings.hooks must be an object')

    ups_groups = hooks.setdefault('UserPromptSubmit', [])
    ptu_groups = hooks.setdefault('PreToolUse', [])
    for name, groups in (('UserPromptSubmit', ups_groups), ('PreToolUse', ptu_groups)):
        if not isinstance(groups, list):
            raise ValueError(f'settings.hooks.{name} must be a list')

    already = _contains_aingram_entry(ups_groups) and _contains_aingram_entry(ptu_groups)
    if already:
        return InstallResult(installed=False)

    if not _contains_aingram_entry(ups_groups):
        ups_groups.append(_aingram_group(hook_script))
    if not _contains_aingram_entry(ptu_groups):
        ptu_groups.append(_matcher_group(hook_script, tool_matchers))

    tmp = settings_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(tmp, settings_path)
    return InstallResult(installed=True)


def uninstall_hooks(*, settings_path: Path) -> UninstallResult:
    if not settings_path.exists():
        return UninstallResult(removed=False)
    data = json.loads(settings_path.read_text(encoding='utf-8'))
    hooks = data.get('hooks')
    if not isinstance(hooks, dict):
        return UninstallResult(removed=False)
    removed = False
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        cleaned = _strip_aingram_entries(groups)
        if len(cleaned) != len(groups):
            removed = True
        if cleaned:
            hooks[event] = cleaned
        else:
            del hooks[event]
    if not hooks:
        data.pop('hooks', None)
    tmp = settings_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(tmp, settings_path)
    return UninstallResult(removed=removed)
