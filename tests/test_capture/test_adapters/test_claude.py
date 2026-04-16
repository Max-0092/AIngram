import time

from aingram.capture.adapters.claude import ClaudeCodeAdapter
from aingram.capture.config import CaptureConfig


class TestClaudeCodeAdapter:
    def setup_method(self):
        self.adapter = ClaudeCodeAdapter(CaptureConfig())

    def test_tool_name(self):
        assert self.adapter.tool_name == 'claude_code'

    def test_parse_user_message(self):
        payload = {
            'session_id': 'sess-abc',
            'type': 'user_prompt',
            'message': 'fix the bug in auth.py',
            'timestamp': time.time(),
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].source_tool == 'claude_code'
        assert records[0].user_prompt == 'fix the bug in auth.py'
        assert records[0].session_id == 'sess-abc'

    def test_parse_assistant_response(self):
        payload = {
            'session_id': 'sess-abc',
            'type': 'assistant_response',
            'message': 'I fixed the bug by...',
            'timestamp': time.time(),
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].assistant_response == 'I fixed the bug by...'

    def test_parse_unknown_type_returns_empty(self):
        payload = {
            'session_id': 'sess-abc',
            'type': 'unknown_event',
            'timestamp': time.time(),
        }
        assert self.adapter.parse_payload(payload) == []

    def test_parse_hook_user_prompt_submit(self):
        payload = {
            'session_id': 'sess-hook',
            'hook_event_name': 'UserPromptSubmit',
            'prompt': 'explain how recall works',
            'cwd': '/home/user/project',
            'transcript_path': '/tmp/transcript.json',
            'permission_mode': 'default',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].source_tool == 'claude_code'
        assert records[0].user_prompt == 'explain how recall works'
        assert records[0].session_id == 'sess-hook'
        assert records[0].project_path == '/home/user/project'

    def test_non_research_post_tool_use_skipped(self):
        # Implementation mechanics — not decisions, not research.
        for tool in ('Edit', 'Bash', 'Write', 'Read', 'Grep', 'Glob', 'TaskUpdate'):
            payload = {
                'session_id': 'sess-hook',
                'hook_event_name': 'PostToolUse',
                'tool_name': tool,
                'tool_input': {'file_path': '/src/main.py'},
                'tool_response': {'content': 'result'},
                'tool_use_id': 'tu-123',
            }
            records = self.adapter.parse_payload(payload)
            assert records == [], f'PostToolUse/{tool} should be skipped'

    def test_web_search_captured(self):
        payload = {
            'session_id': 'sess-hook',
            'hook_event_name': 'PostToolUse',
            'tool_name': 'WebSearch',
            'tool_input': {'query': 'sqlite-vec vector search performance'},
            'tool_response': {
                'results': [
                    {'title': 'sqlite-vec docs', 'url': 'https://example.com', 'snippet': 'Fast KNN search'},
                ]
            },
            'tool_use_id': 'tu-ws',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert 'sqlite-vec vector search performance' in records[0].user_prompt
        assert 'sqlite-vec docs' in (records[0].assistant_response or '')

    def test_web_fetch_captured(self):
        payload = {
            'session_id': 'sess-hook',
            'hook_event_name': 'PostToolUse',
            'tool_name': 'WebFetch',
            'tool_input': {
                'url': 'https://example.com/docs',
                'prompt': 'Extract the API endpoint list',
            },
            'tool_response': {'content': 'API endpoints: /v1/search, /v1/store'},
            'tool_use_id': 'tu-wf',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert 'https://example.com/docs' in records[0].user_prompt
        assert 'Extract the API endpoint list' in records[0].user_prompt

    def test_agent_dispatch_captured(self):
        payload = {
            'session_id': 'sess-hook',
            'hook_event_name': 'PostToolUse',
            'tool_name': 'Agent',
            'tool_input': {
                'description': 'Research vector DB benchmarks',
                'subagent_type': 'Explore',
                'prompt': 'Find performance comparisons...',
            },
            'tool_response': {'result': 'Found: chroma is 2x slower than sqlite-vec'},
            'tool_use_id': 'tu-ag',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert 'Research vector DB benchmarks' in records[0].user_prompt
        assert 'Explore' in records[0].user_prompt

    def test_stop_event_captures_last_assistant_message(self):
        payload = {
            'session_id': 'sess-stop',
            'hook_event_name': 'Stop',
            'last_assistant_message': 'Option A is recommended because it avoids all public exposure. The provider stays local and only results get submitted.',
            'cwd': '/home/user/project',
            'stop_hook_active': False,
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert 'Option A is recommended' in records[0].user_prompt
        assert records[0].session_id == 'sess-stop'
        assert records[0].project_path == '/home/user/project'

    def test_stop_event_empty_message_skipped(self):
        payload = {
            'session_id': 'sess-stop',
            'hook_event_name': 'Stop',
            'last_assistant_message': '',
            'stop_hook_active': False,
        }
        assert self.adapter.parse_payload(payload) == []

    def test_stop_event_truncates_long_messages(self):
        long_msg = 'x' * 9000
        payload = {
            'session_id': 'sess-stop',
            'hook_event_name': 'Stop',
            'last_assistant_message': long_msg,
            'stop_hook_active': False,
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert len(records[0].user_prompt) == 6000

    def test_installation_instructions_contains_curl(self):
        instructions = self.adapter.get_installation_instructions()
        assert 'localhost:7749' in instructions
        assert 'claude-code' in instructions

    def test_health_check_returns_tool_health(self):
        h = self.adapter.health_check()
        assert h.tool_name == 'claude_code'
        assert h.tier == 1
