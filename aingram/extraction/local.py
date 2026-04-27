"""LocalExtractor — structured extraction via Ollama.

Uses httpx directly against Ollama's /api/generate endpoint. JSON parsing relies
on the system prompt rather than grammar-constrained format mode, enabling
compatibility with thinking models via options.think=false.
"""

from __future__ import annotations

import json
import logging

import httpx

from aingram.types import (
    EntryType,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)

logger = logging.getLogger(__name__)

_VALID_ENTRY_TYPES = {e.value for e in EntryType}

_SYSTEM_PROMPT = (
    "You are an AI memory extraction system. Given text from an agent's reasoning, "
    'extract structured metadata as JSON with these fields:\n'
    '- entry_type: one of observation, hypothesis, method, result, lesson, decision, meta\n'
    '- confidence: float 0-1, how confident the content is\n'
    '- relevance: float 0-1, how important for long-term memory\n'
    '- entities: array of {name, type} objects for named entities\n'
    '- relationships: array of {source, target, type, fact} objects\n'
    'Output ONLY valid JSON.'
)

_DEFAULT_BASE_URL = 'http://localhost:11434'


class LocalExtractor:
    """Extract memory metadata using a local Ollama model.

    Sends a structured system prompt and parses the model's response as JSON.
    Owns its httpx.Client — call close() or use as a context manager.
    """

    def __init__(
        self,
        *,
        model: str = 'aingram-extractor',
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip('/')
        self._timeout = timeout
        self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LocalExtractor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _generate(self, prompt: str, *, system: str | None = None) -> dict | None:
        payload: dict = {
            'model': self._model,
            'prompt': prompt,
            'stream': False,
            'options': {'think': False},
        }
        if system is not None:
            payload['system'] = system
        try:
            response = self._client.post('/api/generate', json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.warning('Local extraction HTTP error: %s', e)
            return None

        try:
            raw = response.json().get('response', '')
        except ValueError as e:
            logger.warning('Local extraction: invalid response envelope: %s', e)
            return None

        # Thinking models with options.think=false can emit only a hidden
        # reasoning block and no visible output, leaving 'response' empty.
        # Treat as a soft miss — the caller already handles None gracefully.
        if not raw.strip():
            logger.warning('Local extraction: model returned empty response')
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning('Local extraction: non-JSON response (%s): %.160r', e.msg, raw)
            return None

    def warmup(self) -> bool:
        """Send a minimal request to ensure the model is loaded. Returns True on success."""
        try:
            resp = self._client.post(
                '/api/generate',
                json={
                    'model': self._model,
                    'prompt': 'hi',
                    'stream': False,
                    'options': {'think': False},
                },
            )
            resp.raise_for_status()
            return True
        except Exception:
            logger.warning('Model warmup failed — model may not be available', exc_info=True)
            return False

    def extract(self, text: str, entity_types: list[str] | None = None) -> list[ExtractedEntity]:
        """Extract entities from text via local Ollama model."""
        data = self._generate(text, system=_SYSTEM_PROMPT)
        if data is None:
            return []
        return self._parse_entities(data)

    def extract_full(self, text: str) -> ExtractionResult:
        """Extract full structured metadata (entry_type, confidence, relationships)."""
        data = self._generate(text, system=_SYSTEM_PROMPT)
        if data is None:
            return self._default_result()
        return self._parse_response(data)

    def _parse_entities(self, data: dict) -> list[ExtractedEntity]:
        """Extract just the entity list from a parsed Ollama response."""
        confidence = max(0.0, min(1.0, float(data.get('confidence', 0.5))))
        entities = []
        for e in data.get('entities', []):
            if isinstance(e, dict) and 'name' in e and 'type' in e:
                entities.append(
                    ExtractedEntity(
                        name=e['name'],
                        entity_type=e['type'],
                        score=confidence,
                    )
                )
        return entities

    def _parse_response(self, data: dict) -> ExtractionResult:
        """Parse Ollama JSON response into ExtractionResult with validation."""
        entry_type = data.get('entry_type', 'observation')
        if entry_type not in _VALID_ENTRY_TYPES:
            entry_type = 'observation'

        confidence = max(0.0, min(1.0, float(data.get('confidence', 0.5))))
        relevance = max(0.0, min(1.0, float(data.get('relevance', 0.5))))

        entities = self._parse_entities(data)

        relationships = []
        for r in data.get('relationships', []):
            if isinstance(r, dict) and 'source' in r and 'target' in r and 'type' in r:
                relationships.append(
                    ExtractedRelationship(
                        source=r['source'],
                        target=r['target'],
                        relation_type=r['type'],
                        fact=r.get('fact'),
                    )
                )

        return ExtractionResult(
            entry_type=entry_type,
            confidence=confidence,
            relevance=relevance,
            entities=entities,
            relationships=relationships,
        )

    @staticmethod
    def _default_result() -> ExtractionResult:
        return ExtractionResult(entry_type='observation', confidence=0.5, relevance=0.5)
