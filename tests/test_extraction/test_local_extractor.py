"""LocalExtractor tests — Ollama-backed extraction without JSON format mode."""

import json
from unittest.mock import MagicMock, patch


def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {'response': json.dumps(data)}
    mock.raise_for_status = MagicMock()
    return mock


def _patch_client_post(response_or_exc):
    """Patch httpx.Client.post with a response or raising exception."""
    if isinstance(response_or_exc, Exception):
        return patch('httpx.Client.post', side_effect=response_or_exc)
    return patch('httpx.Client.post', return_value=response_or_exc)


class TestLocalExtractorExtract:
    """Tests for extract() — returns list[ExtractedEntity]."""

    def test_returns_entity_list(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({
            'confidence': 0.8,
            'entities': [{'name': 'pool', 'type': 'component'}],
        })
        with _patch_client_post(mock_response):
            extractor = LocalExtractor(model='test-model')
            result = extractor.extract('Connection pool causes latency')

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == 'pool'
        assert result[0].entity_type == 'component'

    def test_empty_entities_returns_empty_list(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'confidence': 0.9, 'entities': []})
        with _patch_client_post(mock_response):
            result = LocalExtractor(model='test').extract('test')

        assert result == []

    def test_http_error_returns_empty_list(self):
        from aingram.extraction.local import LocalExtractor

        with _patch_client_post(Exception('connection refused')):
            result = LocalExtractor(model='test').extract('test')

        assert result == []

    def test_malformed_json_returns_empty_list(self):
        from aingram.extraction.local import LocalExtractor

        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {'response': 'not valid json{{{'}
        mock.raise_for_status = MagicMock()
        with _patch_client_post(mock):
            result = LocalExtractor(model='test').extract('test')

        assert result == []

    def test_empty_response_returns_empty_list_without_traceback(self, caplog):
        """Thinking-model empty-response case: quiet one-line warning, no stacktrace."""
        import logging

        from aingram.extraction.local import LocalExtractor

        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {'response': ''}
        mock.raise_for_status = MagicMock()
        with _patch_client_post(mock), caplog.at_level(logging.WARNING, logger='aingram.extraction.local'):
            result = LocalExtractor(model='test').extract('test')

        assert result == []
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert 'empty response' in warnings[0].getMessage().lower()
        # No exception info attached — that was the whole point of the cleanup.
        assert warnings[0].exc_info is None

    def test_no_format_json_in_request(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'entities': []})
        with patch('httpx.Client.post', return_value=mock_response) as mock_post:
            LocalExtractor(model='test').extract('test text')

        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        assert 'format' not in payload
        assert payload['options'] == {'think': False}

    def test_uses_system_prompt(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'entities': []})
        with patch('httpx.Client.post', return_value=mock_response) as mock_post:
            LocalExtractor(model='test').extract('test text')

        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        assert 'system' in payload
        assert len(payload['system']) > 20

    def test_custom_base_url(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'entities': []})
        with patch('httpx.Client.post', return_value=mock_response) as mock_post:
            extractor = LocalExtractor(model='test', base_url='http://custom:9999')
            extractor.extract('test')

        # Client is constructed with the base_url; the post call uses a relative path.
        assert extractor._client.base_url.host == 'custom'
        assert extractor._client.base_url.port == 9999
        path = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get('url', '')
        assert path.endswith('/api/generate')

    def test_reuses_http_client(self):
        """Regression: httpx.Client should persist across calls, not reconstruct per-request."""
        from aingram.extraction.local import LocalExtractor

        extractor = LocalExtractor(model='test')
        mock_response = _make_response({'entities': []})
        with patch.object(extractor._client, 'post', return_value=mock_response) as mock_post:
            extractor.extract('first')
            extractor.extract('second')

        assert mock_post.call_count == 2


class TestLocalExtractorExtractFull:
    """Tests for extract_full() — returns ExtractionResult with all fields."""

    def test_returns_full_result(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({
            'entry_type': 'observation',
            'confidence': 0.8,
            'relevance': 0.7,
            'entities': [{'name': 'pool', 'type': 'component'}],
            'relationships': [
                {'source': 'pool', 'target': 'gateway', 'type': 'uses', 'fact': 'pool uses gw'}
            ],
        })
        with _patch_client_post(mock_response):
            result = LocalExtractor(model='test-model').extract_full('Connection pool causes latency')

        assert result.entry_type == 'observation'
        assert result.confidence == 0.8
        assert result.relevance == 0.7
        assert len(result.entities) == 1
        assert result.entities[0].name == 'pool'
        assert len(result.relationships) == 1
        assert result.relationships[0].source == 'pool'

    def test_invalid_entry_type_defaults_to_observation(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'entry_type': 'bogus_type', 'confidence': 0.5, 'relevance': 0.5})
        with _patch_client_post(mock_response):
            result = LocalExtractor(model='test').extract_full('test')

        assert result.entry_type == 'observation'

    def test_clamps_confidence_and_relevance(self):
        from aingram.extraction.local import LocalExtractor

        mock_response = _make_response({'entry_type': 'observation', 'confidence': 5.0, 'relevance': -1.0})
        with _patch_client_post(mock_response):
            result = LocalExtractor(model='test').extract_full('test')

        assert result.confidence == 1.0
        assert result.relevance == 0.0

    def test_http_error_returns_default(self):
        from aingram.extraction.local import LocalExtractor

        with _patch_client_post(Exception('connection refused')):
            result = LocalExtractor(model='test').extract_full('test')

        assert result.entry_type == 'observation'
        assert result.confidence == 0.5


class TestLocalExtractorProtocol:
    def test_implements_entity_extractor_protocol(self):
        from aingram.extraction.local import LocalExtractor
        from aingram.processing.protocols import EntityExtractor

        assert isinstance(LocalExtractor(model='test'), EntityExtractor)
