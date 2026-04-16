from __future__ import annotations

import json
import time

from aingram.capture.adapters.base import ToolAdapter
from aingram.capture.types import CaptureRecord, ToolHealth

# Research tools: Claude actively gathering information to inform a decision.
# We capture the intent (query/URL/description) and a brief result summary —
# not the raw fetched content.
_RESEARCH_TOOLS = frozenset({'WebSearch', 'WebFetch', 'Agent'})
_RESULT_PREVIEW_LEN = 800


def _format_research_record(tool_name: str, tool_input: dict, tool_response: dict) -> tuple[str, str]:
    """Return (user_prompt, assistant_response) for a research tool call."""
    if tool_name == 'WebSearch':
        query = tool_input.get('query', '')
        prompt = f'Research: {query}'
        # Extract result titles + snippets, skip raw HTML
        results = tool_response.get('results', []) if tool_response else []
        if isinstance(results, list):
            lines = [
                f'- {r.get("title", "")} ({r.get("url", "")}): {r.get("snippet", r.get("description", ""))}'
                for r in results[:5]
                if isinstance(r, dict)
            ]
            response = '\n'.join(lines)[:_RESULT_PREVIEW_LEN]
        else:
            response = json.dumps(tool_response, default=str)[:_RESULT_PREVIEW_LEN]
        return prompt, response

    if tool_name == 'WebFetch':
        url = tool_input.get('url', '')
        intent = tool_input.get('prompt', '')
        prompt = f'Fetched: {url}' + (f' — {intent}' if intent else '')
        # Raw content is noise; the intent + URL is the signal
        content = tool_response.get('content', '') if tool_response else ''
        response = (str(content)[:_RESULT_PREVIEW_LEN] if content else '')
        return prompt, response

    if tool_name == 'Agent':
        description = tool_input.get('description', tool_input.get('prompt', ''))
        subagent_type = tool_input.get('subagent_type', '')
        prompt = f'Delegated ({subagent_type}): {description}' if subagent_type else f'Delegated: {description}'
        result = tool_response.get('result', '') if tool_response else ''
        response = str(result)[:_RESULT_PREVIEW_LEN] if result else ''
        return prompt, response

    return '', ''


class ClaudeCodeAdapter(ToolAdapter):
    tool_name = 'claude_code'

    def parse_payload(self, raw: dict) -> list[CaptureRecord]:
        session_id = raw.get('session_id', '')
        ts = raw.get('timestamp', time.time())
        event_name = raw.get('hook_event_name', '')
        # Legacy format support: "type" field from direct API calls
        legacy_type = raw.get('type', '')

        if event_name == 'UserPromptSubmit':
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=session_id,
                    user_prompt=raw.get('prompt', ''),
                    project_path=raw.get('cwd'),
                    timestamp=ts,
                )
            ]

        if event_name == 'Stop':
            message = (raw.get('last_assistant_message') or '').strip()
            if not message:
                return []
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=session_id,
                    user_prompt=message[:6000],
                    project_path=raw.get('cwd'),
                    timestamp=ts,
                )
            ]

        if event_name == 'PostToolUse':
            tool_name = raw.get('tool_name', '')
            if tool_name not in _RESEARCH_TOOLS:
                # All other tool calls are implementation mechanics, not decisions.
                return []
            tool_input = raw.get('tool_input', {})
            tool_response = raw.get('tool_response', {})
            user_prompt, assistant_response = _format_research_record(
                tool_name, tool_input, tool_response
            )
            if not user_prompt:
                return []
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=session_id,
                    user_prompt=user_prompt,
                    assistant_response=assistant_response or None,
                    project_path=raw.get('cwd'),
                    timestamp=ts,
                )
            ]

        # Legacy direct-POST format
        message = raw.get('message', '')
        if legacy_type == 'user_prompt':
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=session_id,
                    user_prompt=message,
                    timestamp=ts,
                )
            ]
        if legacy_type == 'assistant_response':
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=session_id,
                    user_prompt='',
                    assistant_response=message,
                    timestamp=ts,
                )
            ]
        return []

    def get_installation_instructions(self) -> str:
        return (
            'Add to ~/.claude/settings.json under "hooks":\n\n'
            '{\n'
            '  "hooks": {\n'
            '    "UserPromptSubmit": [{\n'
            '      "matcher": "",\n'
            '      "hooks": [{\n'
            '        "type": "command",\n'
            '        "command": "curl -s -X POST http://localhost:7749/capture/claude-code/hook '
            "-H 'Content-Type: application/json' -d @-\"\n"
            '      }]\n'
            '    }],\n'
            '    "PostToolUse": [{\n'
            '      "matcher": "WebSearch|WebFetch|Agent",\n'
            '      "hooks": [{\n'
            '        "type": "command",\n'
            '        "command": "curl -s -X POST http://localhost:7749/capture/claude-code/hook '
            "-H 'Content-Type: application/json' -d @-\"\n"
            '      }]\n'
            '    }]\n'
            '  }\n'
            '}'
        )

    def health_check(self) -> ToolHealth:
        return ToolHealth(tool_name=self.tool_name, connected=True, tier=1)
