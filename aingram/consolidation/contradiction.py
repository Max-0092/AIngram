# aingram/consolidation/contradiction.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from itertools import combinations

from aingram.processing.protocols import ContradictionClassifier, LLMProcessor
from aingram.security.bounds import sanitize_for_prompt
from aingram.storage.engine import StorageEngine
from aingram.types import ContradictionVerdict, MemoryEntry

logger = logging.getLogger(__name__)

_SUPERSEDED_IMPORTANCE_FACTOR = 0.3
_MAX_PAIRS_PER_ENTITY = 50
_MAX_TOTAL_PAIRS = 200

# Entry type pairs where supersession is natural (not a contradiction)
# A result naturally supersedes a hypothesis — that's the scientific method.
_NATURAL_SUPERSESSION_PAIRS = {
    frozenset({'hypothesis', 'result'}),
    frozenset({'hypothesis', 'lesson'}),
    frozenset({'method', 'result'}),
    frozenset({'decision', 'result'}),
}

CONTRADICTION_SYSTEM_PROMPT = (
    'You are a fact-checker analyzing statements for contradictions. '
    'Compare the two statements and determine if they contradict each other. '
    'Output ONLY valid JSON with keys: contradicts (bool), superseded_index (0 or 1, '
    'which statement is outdated). If no contradiction, just: {"contradicts": false}'
)

CONTRADICTION_USER_PROMPT = (
    'Statement 0: "{text_a}"\nStatement 1: "{text_b}"\n\nDo these statements contradict each other?'
)


@dataclass
class ContradictionResult:
    contradictions_found: int
    contradictions_resolved: int


class LLMContradictionClassifier:
    """Contradiction classifier using an LLM via the LLMProcessor protocol."""

    def __init__(self, llm: LLMProcessor) -> None:
        self._llm = llm

    def classify(self, text_a: str, text_b: str) -> ContradictionVerdict:
        prompt = CONTRADICTION_USER_PROMPT.format(text_a=text_a, text_b=text_b)
        try:
            raw = self._llm.complete(prompt, system=CONTRADICTION_SYSTEM_PROMPT)
            data = json.loads(raw)
        except Exception:
            return ContradictionVerdict(contradicts=False, confidence=0.0)

        if not isinstance(data, dict):
            return ContradictionVerdict(contradicts=False, confidence=0.0)
        if not isinstance(data.get('contradicts'), bool):
            return ContradictionVerdict(contradicts=False, confidence=0.0)

        return ContradictionVerdict(
            contradicts=data['contradicts'],
            confidence=1.0,
            superseded_index=data.get('superseded_index'),
        )


class ContradictionDetector:
    def __init__(
        self,
        engine: StorageEngine,
        *,
        classifier: ContradictionClassifier | None = None,
    ) -> None:
        self._engine = engine
        self._classifier = classifier

    def detect_and_resolve(self) -> ContradictionResult:
        if self._classifier is None:
            return ContradictionResult(contradictions_found=0, contradictions_resolved=0)

        entity_pairs = self._engine.get_entity_entry_pairs()
        if not entity_pairs:
            return ContradictionResult(contradictions_found=0, contradictions_resolved=0)

        # Group entry_ids by entity
        entity_entries: dict[str, list[str]] = {}
        for entity_id, entry_id in entity_pairs:
            entity_entries.setdefault(entity_id, []).append(entry_id)

        candidate_pairs = self._collect_candidate_pairs(entity_entries)
        if not candidate_pairs:
            return ContradictionResult(contradictions_found=0, contradictions_resolved=0)

        # Fetch all involved entries in a single query
        unique_ids = list({eid for pair in candidate_pairs for eid in pair})
        by_id = {e.entry_id: e for e in self._engine.get_entries_by_ids(unique_ids)}

        # Filter natural supersession pairs before hitting the classifier
        classifier_pairs: list[tuple[MemoryEntry, MemoryEntry]] = []
        for id_a, id_b in candidate_pairs:
            entry_a = by_id.get(id_a)
            entry_b = by_id.get(id_b)
            if entry_a is None or entry_b is None:
                continue
            type_pair = frozenset({str(entry_a.entry_type), str(entry_b.entry_type)})
            if type_pair in _NATURAL_SUPERSESSION_PAIRS:
                continue
            classifier_pairs.append((entry_a, entry_b))

        if not classifier_pairs:
            return ContradictionResult(contradictions_found=0, contradictions_resolved=0)

        verdicts = self._classify_pairs(classifier_pairs)

        found = 0
        resolved = 0
        updates: list[tuple[str, float]] = []
        for (entry_a, entry_b), verdict in zip(classifier_pairs, verdicts):
            superseded = self._resolve_verdict(entry_a, entry_b, verdict)
            if superseded is None:
                continue
            found += 1
            updates.append(
                (superseded.entry_id, superseded.importance * _SUPERSEDED_IMPORTANCE_FACTOR)
            )
            resolved += 1

        if updates:
            self._engine.batch_update_entry_importance(updates)

        if len(candidate_pairs) >= _MAX_TOTAL_PAIRS:
            logger.info(
                'Contradiction detection hit global cap (%d pairs); '
                'remaining pairs deferred to next consolidation run',
                _MAX_TOTAL_PAIRS,
            )

        return ContradictionResult(contradictions_found=found, contradictions_resolved=resolved)

    def _collect_candidate_pairs(
        self, entity_entries: dict[str, list[str]]
    ) -> list[tuple[str, str]]:
        # Note: natural-supersession filtering happens after this step (in detect_and_resolve)
        # because entry types aren't available here without an extra DB query. This means
        # supersession pairs count toward _MAX_TOTAL_PAIRS, potentially deferring valid
        # contradiction pairs to the next consolidation run. Acceptable for the current scale.
        checked: set[frozenset[str]] = set()
        pairs: list[tuple[str, str]] = []
        for entry_ids in entity_entries.values():
            if len(pairs) >= _MAX_TOTAL_PAIRS:
                break
            pairs_this_entity = 0
            for id_a, id_b in combinations(entry_ids, 2):
                if len(pairs) >= _MAX_TOTAL_PAIRS:
                    break
                if pairs_this_entity >= _MAX_PAIRS_PER_ENTITY:
                    break
                pair_key = frozenset({id_a, id_b})
                if pair_key in checked:
                    continue
                checked.add(pair_key)
                pairs_this_entity += 1
                pairs.append((id_a, id_b))
        return pairs

    def _classify_pairs(
        self, pairs: list[tuple[MemoryEntry, MemoryEntry]]
    ) -> list[ContradictionVerdict]:
        texts = [
            (sanitize_for_prompt(a.content), sanitize_for_prompt(b.content))
            for a, b in pairs
        ]
        batch_fn = getattr(self._classifier, 'classify_batch', None)
        if callable(batch_fn):
            return list(batch_fn(texts))
        return [self._classifier.classify(a, b) for a, b in texts]

    @staticmethod
    def _resolve_verdict(
        entry_a: MemoryEntry,
        entry_b: MemoryEntry,
        verdict: ContradictionVerdict,
    ) -> MemoryEntry | None:
        if not verdict.contradicts:
            return None
        if verdict.superseded_index is not None:
            if verdict.superseded_index not in (0, 1):
                return None
            ordered = [entry_a, entry_b]
            return ordered[verdict.superseded_index]
        # Recency fallback: older entry is superseded
        return entry_a if entry_a.created_at <= entry_b.created_at else entry_b
