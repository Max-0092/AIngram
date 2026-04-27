# tests/test_cc_hook/test_query.py
from __future__ import annotations

from aingram.cc_hook.query import derive_query


def test_user_prompt_submit_uses_prompt_verbatim() -> None:
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'prompt': 'refactor the worker drain logic',
    }
    assert derive_query(payload) == 'refactor the worker drain logic'


def test_pre_tool_use_edit_combines_file_path_and_diff() -> None:
    payload = {
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Edit',
        'tool_input': {
            'file_path': 'aingram/worker.py',
            'old_string': 'def process_one(self):',
            'new_string': 'def process_one(self) -> bool:',
        },
    }
    q = derive_query(payload)
    assert q is not None
    assert 'aingram/worker.py' in q
    assert 'def process_one' in q


def test_pre_tool_use_edit_truncates_long_strings() -> None:
    payload = {
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Edit',
        'tool_input': {
            'file_path': 'big.py',
            'old_string': 'a' * 1000,
            'new_string': 'b' * 1000,
        },
    }
    q = derive_query(payload)
    assert q is not None
    # file_path + 250 of old + 250 of new + newlines
    assert len(q) <= len('big.py\n') + 250 + 250 + 1


def test_pre_tool_use_write_uses_content() -> None:
    payload = {
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Write',
        'tool_input': {
            'file_path': 'new.py',
            'content': 'print("hello world")',
        },
    }
    q = derive_query(payload)
    assert q is not None
    assert 'new.py' in q
    assert 'hello world' in q


def test_pre_tool_use_notebook_edit_uses_new_source() -> None:
    payload = {
        'hook_event_name': 'PreToolUse',
        'tool_name': 'NotebookEdit',
        'tool_input': {
            'notebook_path': 'analysis.ipynb',
            'new_source': 'import pandas as pd',
        },
    }
    q = derive_query(payload)
    assert q is not None
    assert 'analysis.ipynb' in q
    assert 'pandas' in q


def test_empty_query_returns_none() -> None:
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'prompt': '',
    }
    assert derive_query(payload) is None


def test_under_min_length_returns_none() -> None:
    payload = {
        'hook_event_name': 'UserPromptSubmit',
        'prompt': 'short',
    }
    assert derive_query(payload) is None


def test_unsupported_event_returns_none() -> None:
    payload = {'hook_event_name': 'SessionStart'}
    assert derive_query(payload) is None


def test_pre_tool_use_unmatched_tool_returns_none() -> None:
    payload = {
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Bash',
        'tool_input': {'command': 'ls -la'},
    }
    assert derive_query(payload) is None


def test_pre_tool_use_missing_tool_input_returns_none() -> None:
    payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Edit'}
    assert derive_query(payload) is None
