import json

from aingram.capture.adapters.cursor import CursorAdapter
from aingram.capture.config import CaptureConfig


class TestCursorAdapter:
    def setup_method(self):
        self.adapter = CursorAdapter(CaptureConfig())

    def test_tool_name(self):
        assert self.adapter.tool_name == 'cursor'

    def test_parse_before_submit_prompt(self):
        payload = {
            'hook_event_name': 'beforeSubmitPrompt',
            'conversation_id': 'conv-1',
            'generation_id': 'gen-1',
            'prompt': 'fix the null pointer exception',
            'workspace_roots': ['/home/user/myproject'],
            'attachments': ['file.py'],
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].user_prompt == 'fix the null pointer exception'
        assert records[0].session_id == 'conv-1'
        assert records[0].project_path == '/home/user/myproject'

    def test_parse_after_agent_response(self):
        payload = {
            'hook_event_name': 'afterAgentResponse',
            'conversation_id': 'conv-1',
            'generation_id': 'gen-1',
            'text': 'Fixed the null check in line 42.',
            'model': 'claude-sonnet-4',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].assistant_response == 'Fixed the null check in line 42.'
        assert records[0].model == 'claude-sonnet-4'

    def test_parse_session_start_returns_empty(self):
        payload = {
            'hook_event_name': 'sessionStart',
            'conversation_id': 'conv-1',
        }
        assert self.adapter.parse_payload(payload) == []

    def test_parse_stop_returns_empty(self):
        payload = {
            'hook_event_name': 'stop',
            'conversation_id': 'conv-1',
            'status': 'completed',
        }
        assert self.adapter.parse_payload(payload) == []

    def test_parse_after_agent_thought(self):
        payload = {
            'hook_event_name': 'afterAgentThought',
            'conversation_id': 'conv-1',
            'generation_id': 'gen-7',
            'text': 'Considering whether to search files first.',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        assert records[0].assistant_response == 'Considering whether to search files first.'
        assert 'thought' in (records[0].metadata or '')

    def test_parse_after_agent_thought_empty_dropped(self):
        payload = {
            'hook_event_name': 'afterAgentThought',
            'conversation_id': 'conv-1',
        }
        assert self.adapter.parse_payload(payload) == []

    def test_parse_post_tool_use(self):
        payload = {
            'hook_event_name': 'postToolUse',
            'conversation_id': 'conv-1',
            'generation_id': 'gen-2',
            'tool_name': 'read_file',
            'tool_input': {'path': '/tmp/foo.py'},
            'tool_output': 'def foo(): pass',
            'tool_use_id': 'tu-123',
            'duration': 42,
            'cwd': '/home/user/proj',
            'model': 'claude-sonnet-4',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        rec = records[0]
        assert rec.user_prompt == ''
        assert rec.assistant_response is None
        assert rec.project_path == '/home/user/proj'
        assert rec.model == 'claude-sonnet-4'
        tc = json.loads(rec.tool_calls or '{}')
        assert tc['tool_name'] == 'read_file'
        assert tc['tool_input'] == {'path': '/tmp/foo.py'}
        assert tc['tool_output'] == 'def foo(): pass'
        assert tc['tool_use_id'] == 'tu-123'

    def test_post_tool_use_survives_filter(self):
        payload = {
            'hook_event_name': 'postToolUse',
            'conversation_id': 'conv-1',
            'tool_name': 'grep',
            'tool_input': {'pattern': 'TODO'},
            'tool_output': 'match at line 3',
        }
        records = self.adapter.parse_payload(payload)
        assert len(records) == 1
        filtered = self.adapter.apply_filters(records[0])
        assert filtered is not None
        assert (filtered.tool_calls or '').strip() != ''

    def test_metadata_includes_generation_id(self):
        payload = {
            'hook_event_name': 'beforeSubmitPrompt',
            'conversation_id': 'conv-1',
            'generation_id': 'gen-42',
            'prompt': 'test',
        }
        records = self.adapter.parse_payload(payload)
        assert 'gen-42' in (records[0].metadata or '')

    def test_install_instructions_include_all_events(self):
        text = self.adapter.get_installation_instructions()
        for event in (
            'beforeSubmitPrompt',
            'afterAgentResponse',
            'afterAgentThought',
            'postToolUse',
        ):
            assert event in text

    def test_health_check(self):
        h = self.adapter.health_check()
        assert h.tool_name == 'cursor'
        assert h.tier == 2
