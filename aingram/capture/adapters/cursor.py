from __future__ import annotations

import json
import sys
import time

from aingram.capture.adapters.base import ToolAdapter
from aingram.capture.types import CaptureRecord, ToolHealth


class CursorAdapter(ToolAdapter):
    tool_name = 'cursor'

    def parse_payload(self, raw: dict) -> list[CaptureRecord]:
        event = raw.get('hook_event_name', '')
        conversation_id = raw.get('conversation_id', '')
        generation_id = raw.get('generation_id', '')
        ts = raw.get('timestamp', time.time())
        cwd = raw.get('cwd')
        workspace_roots = raw.get('workspace_roots', [])
        project_path = cwd or (workspace_roots[0] if workspace_roots else None)

        if event == 'beforeSubmitPrompt':
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=conversation_id,
                    user_prompt=raw.get('prompt', ''),
                    project_path=project_path,
                    timestamp=ts,
                    metadata=json.dumps(
                        {
                            'event': event,
                            'generation_id': generation_id,
                            'attachments': raw.get('attachments', []),
                        }
                    ),
                )
            ]
        if event == 'afterAgentResponse':
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=conversation_id,
                    user_prompt='',
                    assistant_response=raw.get('text', ''),
                    model=raw.get('model'),
                    project_path=project_path,
                    timestamp=ts,
                    metadata=json.dumps({'event': event, 'generation_id': generation_id}),
                )
            ]
        if event == 'afterAgentThought':
            thought = raw.get('text', '') or raw.get('thought', '')
            if not thought:
                return []
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=conversation_id,
                    user_prompt='',
                    assistant_response=thought,
                    model=raw.get('model'),
                    project_path=project_path,
                    timestamp=ts,
                    metadata=json.dumps(
                        {'event': event, 'generation_id': generation_id, 'kind': 'thought'}
                    ),
                )
            ]
        if event == 'postToolUse':
            tool_name = raw.get('tool_name', '')
            tool_calls = json.dumps(
                {
                    'tool_name': tool_name,
                    'tool_input': raw.get('tool_input'),
                    'tool_output': raw.get('tool_output'),
                    'tool_use_id': raw.get('tool_use_id'),
                    'duration': raw.get('duration'),
                }
            )
            return [
                CaptureRecord(
                    source_tool=self.tool_name,
                    session_id=conversation_id,
                    user_prompt='',
                    assistant_response=None,
                    tool_calls=tool_calls,
                    model=raw.get('model'),
                    project_path=project_path,
                    timestamp=ts,
                    metadata=json.dumps(
                        {
                            'event': event,
                            'generation_id': generation_id,
                            'tool_name': tool_name,
                        }
                    ),
                )
            ]
        # stop / sessionEnd / sessionStart are lifecycle markers with no content
        # worth persisting as memory entries — they're ignored on purpose.
        return []

    def get_installation_instructions(self) -> str:
        # Cursor runs hook commands through the platform's default shell.
        # On Windows that's PowerShell, where:
        #   * `curl` is an alias for Invoke-WebRequest (not the real curl)
        #   * `@-` is parsed as a splat operator on variable `-` → parse error
        #   * single-quoted header args work, but consistency with the `@-` fix
        #     is cleaner if we switch everything to double quotes.
        # So on Windows we emit `curl.exe` explicitly and quote `"@-"` as a
        # literal string; on POSIX shells the classic single-quoted form works.
        if sys.platform == 'win32':
            cmd = (
                'curl.exe -s -X POST \\"http://localhost:7749/capture/cursor/hook\\" '
                '-H \\"Content-Type: application/json\\" -d \\"@-\\"'
            )
        else:
            cmd = (
                "curl -s -X POST http://localhost:7749/capture/cursor/hook "
                "-H 'Content-Type: application/json' -d @-"
            )
        # Subscribe to every event that carries conversation or tool-use content.
        # Agent-mode loops can run many tool calls without a new user prompt, so
        # postToolUse is what captures autonomous work; afterAgentThought catches
        # the model's reasoning turns when Cursor emits them.
        events = [
            'beforeSubmitPrompt',
            'afterAgentResponse',
            'afterAgentThought',
            'postToolUse',
        ]
        blocks = ',\n'.join(
            f'    "{event}": [{{\n      "command": "{cmd}"\n    }}]' for event in events
        )
        return (
            'Add to .cursor/hooks.json (project) or ~/.cursor/hooks.json (global):\n\n'
            '{\n'
            '  "version": 1,\n'
            '  "hooks": {\n'
            f'{blocks}\n'
            '  }\n'
            '}\n\n'
            'Requires Cursor >= 1.7 (hooks beta).'
        )

    def health_check(self) -> ToolHealth:
        return ToolHealth(tool_name=self.tool_name, connected=True, tier=2)
