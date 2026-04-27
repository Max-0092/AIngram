# aingram/cc_hook/query.py
from __future__ import annotations

from typing import Any

_MIN_QUERY_LEN = 8
_EDIT_HALF = 250  # bytes of old + bytes of new
_WRITE_CAP = 500


def _derive_pre_tool_use(payload: dict[str, Any]) -> str | None:
    tool_name = payload.get('tool_name')
    tool_input = payload.get('tool_input')
    if not tool_name or not isinstance(tool_input, dict):
        return None

    if tool_name == 'Edit':
        file_path = tool_input.get('file_path', '')
        old_s = str(tool_input.get('old_string', ''))[:_EDIT_HALF]
        new_s = str(tool_input.get('new_string', ''))[:_EDIT_HALF]
        if not file_path:
            return None
        return f'{file_path}\n{old_s}{new_s}'

    if tool_name == 'Write':
        file_path = tool_input.get('file_path', '')
        content = str(tool_input.get('content', ''))[:_WRITE_CAP]
        if not file_path:
            return None
        return f'{file_path}\n{content}'

    if tool_name == 'NotebookEdit':
        notebook_path = tool_input.get('notebook_path', '')
        new_source = str(tool_input.get('new_source', ''))[:_WRITE_CAP]
        if not notebook_path:
            return None
        return f'{notebook_path}\n{new_source}'

    # Generic fallback for other matched tools: extract file path + first string value.
    path = str(tool_input.get('file_path') or tool_input.get('notebook_path') or '')
    snippet = next(
        (str(v)[:_WRITE_CAP] for v in tool_input.values() if isinstance(v, str) and v),
        '',
    )
    result = f'{path}\n{snippet}'.strip() if path or snippet else None
    return result


def derive_query(payload: dict[str, Any]) -> str | None:
    """Return a query string for the given CC hook payload, or None to skip."""
    event = payload.get('hook_event_name')
    if event == 'UserPromptSubmit':
        query = str(payload.get('prompt', '') or '').strip()
    elif event == 'PreToolUse':
        query = _derive_pre_tool_use(payload)
    else:
        return None

    if query is None:
        return None
    query = query.strip()
    if len(query) < _MIN_QUERY_LEN:
        return None
    return query
