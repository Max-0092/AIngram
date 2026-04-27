# aingram/worker.py
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from aingram.graph.builder import GraphBuilder
from aingram.processing.protocols import EntityExtractor, LLMProcessor
from aingram.storage.engine import StorageEngine
from aingram.types import ExtractedEntity, ExtractionResult

logger = logging.getLogger(__name__)

RELATIONSHIP_SYSTEM_PROMPT = (
    'You are a knowledge graph builder. Extract relationships between entities from text. '
    'Output ONLY a valid JSON array. Each element must have keys: source, target, relation, fact. '
    'If no relationships exist, output: []'
)
RELATIONSHIP_USER_PROMPT = 'Entities: {entities}\n\nText: "{content}"\n\nExtract relationships:'


class BackgroundWorker:
    def __init__(
        self,
        engine: StorageEngine | None = None,
        *,
        db_path: str | None = None,
        extractor: EntityExtractor,
        llm: LLMProcessor | None = None,
        entity_types: list[str] | None = None,
        poll_interval: float = 0.1,
        concurrency: int = 1,
        training_logger=None,
    ) -> None:
        if engine is not None:
            self._engine = engine
            self._owns_engine = False
        elif db_path is not None:
            self._engine = StorageEngine(db_path)
            self._owns_engine = True
        else:
            raise ValueError('Either engine or db_path must be provided')

        self._extractor = extractor
        self._llm = llm
        self._training_logger = training_logger
        self._entity_types = entity_types or [
            'person',
            'organization',
            'location',
            'project',
            'technology',
        ]
        self._poll_interval = poll_interval
        self._concurrency = max(1, concurrency)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._builder = GraphBuilder(self._engine)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._owns_engine:
            self._engine.close()

    def process_one(self) -> bool:
        task = self._engine.dequeue_task()
        if task is None:
            return False
        self._execute_task(*task)
        return True

    def drain(
        self,
        *,
        progress_callback: Callable[[], None] | None = None,
    ) -> int:
        """Drain all pending tasks using the configured concurrency; blocks until empty.

        A task may enqueue follow-ups (e.g. extract_entities_v3 → link_graph_v3);
        drain waits until both the pending queue AND all in-flight workers are idle.
        Returns the number of tasks processed.
        """
        if self._concurrency == 1:
            return self._drain_serial(progress_callback)
        return self._drain_parallel(progress_callback)

    def _drain_serial(self, progress_callback: Callable[[], None] | None) -> int:
        done = 0
        consecutive_empty = 0
        while consecutive_empty < 3 and not self._stop_event.is_set():
            if self.process_one():
                done += 1
                consecutive_empty = 0
                if progress_callback is not None:
                    progress_callback()
            else:
                consecutive_empty += 1
                time.sleep(self._poll_interval)
        return done

    def _drain_parallel(self, progress_callback: Callable[[], None] | None) -> int:
        state = {'done': 0, 'active': 0}
        state_lock = threading.Lock()
        local_stop = threading.Event()

        def worker_fn() -> None:
            while not local_stop.is_set() and not self._stop_event.is_set():
                task = self._engine.dequeue_task()
                if task is None:
                    time.sleep(self._poll_interval)
                    continue
                with state_lock:
                    state['active'] += 1
                try:
                    self._execute_task(*task)
                    with state_lock:
                        state['done'] += 1
                    if progress_callback is not None:
                        try:
                            progress_callback()
                        except Exception:
                            logger.warning('progress_callback raised', exc_info=True)
                finally:
                    with state_lock:
                        state['active'] -= 1

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = [pool.submit(worker_fn) for _ in range(self._concurrency)]
            try:
                while not self._stop_event.is_set():
                    time.sleep(self._poll_interval)
                    with state_lock:
                        active = state['active']
                    pending = self._engine.get_pending_task_count()
                    if active == 0 and pending == 0:
                        # Settle: a worker may have dequeued a task (removing it from
                        # pending) but not yet incremented active. One poll_interval is
                        # enough for that window to close and for any follow-up enqueues
                        # to become visible before we declare the queue idle.
                        time.sleep(self._poll_interval)
                        with state_lock:
                            active = state['active']
                        pending = self._engine.get_pending_task_count()
                        if active == 0 and pending == 0:
                            break
            finally:
                local_stop.set()
            for f in futures:
                f.result()
        return state['done']

    def _execute_task(self, task_id: str, task_type: str, payload: dict) -> None:
        try:
            if task_type == 'extract_entities_v3':
                self._handle_extract_entities_v3(payload)
            elif task_type == 'link_graph_v3':
                self._handle_link_graph_v3(payload)
            else:
                logger.warning('Unknown task type: %s', task_type)
            self._engine.complete_task(task_id)
        except Exception as e:
            logger.error('Task %s failed: %s', task_id, e, exc_info=True)
            self._engine.fail_task(task_id, str(e))

    def _run(self) -> None:
        if self._concurrency == 1:
            while not self._stop_event.is_set():
                if not self.process_one():
                    time.sleep(self._poll_interval)
            return

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = [pool.submit(self._worker_loop) for _ in range(self._concurrency)]
            for f in futures:
                f.result()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self.process_one():
                time.sleep(self._poll_interval)

    def _handle_extract_entities_v3(self, payload: dict) -> None:
        entry_id = payload['entry_id']
        entry = self._engine.get_entry(entry_id)
        if entry is None:
            logger.warning('Entry %s not found for extraction', entry_id)
            return

        try:
            content_dict = json.loads(entry.content)
            text = content_dict.get('text', entry.content)
        except (json.JSONDecodeError, TypeError):
            text = entry.content

        # Prefer extract_full when the extractor supports it — one LLM call
        # for entities + relationships. Otherwise fall back to entities-only
        # and defer relationship extraction to link_graph_v3.
        if hasattr(self._extractor, 'extract_full'):
            result = self._extractor.extract_full(text)
            self._upsert_entities(entry_id, result.entities)
            self._apply_relationships(entry_id, result.relationships)
            if self._training_logger is not None and result.entities:
                self._training_logger.log(text, result)
            return

        entities = self._extractor.extract(text, self._entity_types)
        entity_names = self._upsert_entities(entry_id, entities)

        if self._training_logger is not None and entities:
            result = ExtractionResult(
                entry_type=str(entry.entry_type),
                confidence=entry.confidence or 0.5,
                relevance=entry.importance,
                entities=[
                    ExtractedEntity(name=e.name, entity_type=e.entity_type, score=e.score)
                    for e in entities
                ],
            )
            self._training_logger.log(text, result)

        if len(entity_names) >= 2 and self._llm is not None:
            self._engine.enqueue_task(
                task_type='link_graph_v3',
                payload={'entry_id': entry_id, 'entity_names': entity_names},
            )

    def _upsert_entities(
        self, entry_id: str, entities: list[ExtractedEntity]
    ) -> list[str]:
        names: list[str] = []
        for e in entities:
            self._builder.upsert_entity(e.name, e.entity_type, source_entry=entry_id)
            names.append(e.name)
        return names

    def _apply_relationships(self, entry_id: str, relationships) -> None:
        for rel in relationships:
            sources = self._engine.find_entities_by_name(rel.source)
            targets = self._engine.find_entities_by_name(rel.target)
            if not sources or not targets:
                continue
            self._builder.add_relationship(
                sources[0].entity_id,
                targets[0].entity_id,
                rel.relation_type,
                fact=rel.fact,
                source_entry=entry_id,
            )

    def _handle_link_graph_v3(self, payload: dict) -> None:
        entry_id = payload['entry_id']
        entity_names = payload.get('entity_names', [])
        entry = self._engine.get_entry(entry_id)
        if entry is None or not entity_names:
            return

        try:
            content_dict = json.loads(entry.content)
            text = content_dict.get('text', entry.content)
        except (json.JSONDecodeError, TypeError):
            text = entry.content

        prompt = RELATIONSHIP_USER_PROMPT.format(
            entities=', '.join(entity_names),
            content=text,
        )
        try:
            raw = self._llm.complete(prompt, system=RELATIONSHIP_SYSTEM_PROMPT)
        except Exception:
            logger.warning('LLM relationship extraction failed', exc_info=True)
            return

        try:
            relationships = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(relationships, list):
            return

        for rel in relationships:
            source_name = rel.get('source')
            target_name = rel.get('target')
            if not source_name or not target_name:
                continue
            found_sources = self._engine.find_entities_by_name(source_name)
            found_targets = self._engine.find_entities_by_name(target_name)
            source_entity = found_sources[0] if found_sources else None
            target_entity = found_targets[0] if found_targets else None

            if source_entity and target_entity:
                self._builder.add_relationship(
                    source_entity.entity_id,
                    target_entity.entity_id,
                    rel.get('relation', 'related'),
                    fact=rel.get('fact'),
                    source_entry=entry_id,
                )
