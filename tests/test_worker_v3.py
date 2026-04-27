"""Background worker v3 tests."""

import threading
import time

import pytest

from aingram.storage.engine import StorageEngine
from aingram.types import (
    AgentSession,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)
from aingram.worker import BackgroundWorker
from tests.conftest import MockExtractor, MockLLM


@pytest.fixture
def engine(tmp_path):
    db = tmp_path / 'test.db'
    eng = StorageEngine(str(db))
    session = AgentSession(
        session_id='s1',
        agent_name='test',
        public_key='a' * 64,
        created_at='2026-01-01T00:00:00+00:00',
    )
    eng.store_session(session)
    eng.store_entry(
        entry_id='e1',
        content_hash='ch1',
        entry_type='observation',
        content='{"text":"Alice met with Bob at Acme Corp"}',
        session_id='s1',
        sequence_num=1,
        prev_entry_id=None,
        signature='sig1',
        created_at='2026-01-01T00:00:00+00:00',
        embedding=[0.1] * 768,
    )
    yield eng
    eng.close()


class TestWorkerV3:
    def test_extract_entities_v3(self, engine):
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=None,
        )
        engine.enqueue_task(
            task_type='extract_entities_v3',
            payload={'entry_id': 'e1'},
        )
        processed = worker.process_one()
        assert processed is True

        # Check entities were created and linked
        entity_ids = engine.get_entity_ids_for_entry('e1')
        assert len(entity_ids) >= 1

    def test_link_graph_v3(self, engine):
        # First create entities
        eid1 = engine.upsert_entity(name='Alice', entity_type='person')
        eid2 = engine.upsert_entity(name='Acme', entity_type='organization')
        engine.link_entity_to_mention(eid1, 'e1')
        engine.link_entity_to_mention(eid2, 'e1')

        rel_json = (
            '[{"source":"Alice","target":"Acme","relation":"works_at",'
            '"fact":"Alice works at Acme"}]'
        )
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=MockLLM(rel_json),
        )
        engine.enqueue_task(
            task_type='link_graph_v3',
            payload={'entry_id': 'e1', 'entity_names': ['Alice', 'Acme']},
        )
        processed = worker.process_one()
        assert processed is True

        # Check relationship was created
        rels = engine.get_relationships_for_entity(eid1)
        assert len(rels) >= 1


class TestWorkerProcessEdgeCases:
    """Edge cases for process_one ported from legacy worker tests."""

    def test_process_one_no_tasks(self, engine):
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor())
        assert worker.process_one() is False

    def test_process_one_skips_deleted_entry(self, engine):
        engine.enqueue_task(
            task_type='extract_entities_v3',
            payload={'entry_id': 'nonexistent'},
        )
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor())
        assert worker.process_one() is True
        # No entities should be created
        assert engine.get_entity_count() == 0

    def test_unknown_task_type_handled_gracefully(self, engine):
        engine.enqueue_task(task_type='unknown_type_xyz', payload={})
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor())
        worker.process_one()  # should not raise
        assert engine.get_pending_task_count() == 0

    def test_extract_enqueues_link_graph_when_llm_available(self, engine):
        llm = MockLLM()
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=llm,
        )
        engine.enqueue_task(
            task_type='extract_entities_v3',
            payload={'entry_id': 'e1'},
        )
        worker.process_one()
        # Should have enqueued a link_graph_v3 task
        task = engine.dequeue_task()
        assert task is not None
        _, task_type, payload = task
        assert task_type == 'link_graph_v3'
        assert payload['entry_id'] == 'e1'

    def test_extract_skips_link_graph_without_llm(self, engine):
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=None,
        )
        engine.enqueue_task(
            task_type='extract_entities_v3',
            payload={'entry_id': 'e1'},
        )
        worker.process_one()
        assert engine.dequeue_task() is None  # no link_graph enqueued

    def test_link_graph_handles_invalid_json(self, engine):
        engine.upsert_entity(name='Alice', entity_type='person')
        engine.upsert_entity(name='Acme', entity_type='organization')
        engine.enqueue_task(
            task_type='link_graph_v3',
            payload={'entry_id': 'e1', 'entity_names': ['Alice', 'Acme']},
        )
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=MockLLM('not valid json'),
        )
        worker.process_one()  # should not raise
        assert engine.get_pending_task_count() == 0

    def test_link_graph_handles_non_list_json(self, engine):
        engine.enqueue_task(
            task_type='link_graph_v3',
            payload={'entry_id': 'e1', 'entity_names': ['Alice', 'Acme']},
        )
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=MockLLM('{"source": "Alice"}'),
        )
        worker.process_one()  # should not raise
        assert engine.get_pending_task_count() == 0


def _seed_entries(engine: StorageEngine, n: int) -> list[str]:
    """Add N entries and enqueue extract tasks for each; return entry IDs."""
    ids = []
    for i in range(n):
        eid = f'drain-e{i}'
        engine.store_entry(
            entry_id=eid,
            content_hash=f'ch{i}',
            entry_type='observation',
            content=f'{{"text":"Alice worked with Bob on Project{i}"}}',
            session_id='s1',
            sequence_num=i + 2,
            prev_entry_id=None,
            signature=f'sig{i}',
            created_at='2026-01-01T00:00:00+00:00',
            embedding=[0.1] * 768,
        )
        engine.enqueue_task(task_type='extract_entities_v3', payload={'entry_id': eid})
        ids.append(eid)
    return ids


class _CountingExtractor:
    """Extractor that sleeps briefly to simulate LLM latency and records concurrent callers."""

    def __init__(self, latency: float = 0.05):
        self._latency = latency
        self._active = 0
        self._lock = threading.Lock()
        self.max_concurrent = 0

    def extract(self, text: str, entity_types: list[str]) -> list[ExtractedEntity]:
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            time.sleep(self._latency)
            return [ExtractedEntity(name='Alice', entity_type='person', score=0.9)]
        finally:
            with self._lock:
                self._active -= 1


class TestWorkerDrain:
    def test_drain_processes_all_pending(self, engine):
        _seed_entries(engine, 8)
        # Plus the fixture's e1
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor(), concurrency=1)
        processed = worker.drain()
        assert processed == 8  # fixture's e1 was not enqueued
        assert engine.get_pending_task_count() == 0

    def test_drain_serial_matches_parallel_count(self, engine):
        _seed_entries(engine, 5)
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor(), concurrency=4)
        processed = worker.drain()
        assert processed == 5
        assert engine.get_pending_task_count() == 0

    def test_drain_parallel_runs_concurrent_workers(self, engine):
        _seed_entries(engine, 6)
        extractor = _CountingExtractor(latency=0.1)
        worker = BackgroundWorker(engine=engine, extractor=extractor, concurrency=3)
        worker.drain()
        # With 3 concurrent workers and 6 slow tasks, we should observe at least 2 in-flight.
        assert extractor.max_concurrent >= 2

    def test_drain_handles_followup_tasks(self, engine):
        """extract_entities_v3 enqueues link_graph_v3 — drain must pick those up too."""
        _seed_entries(engine, 3)
        rel_json = '[{"source":"Alice","target":"Bob","relation":"works_with","fact":"x"}]'
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=MockLLM(rel_json),
            concurrency=2,
        )
        processed = worker.drain()
        # 3 extract tasks + 3 link_graph follow-ups (MockExtractor finds ≥2 entities per entry)
        assert processed == 6
        assert engine.get_pending_task_count() == 0

    def test_drain_progress_callback_fires_per_task(self, engine):
        _seed_entries(engine, 4)
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor(), concurrency=2)
        counter = {'n': 0}
        lock = threading.Lock()

        def _tick():
            with lock:
                counter['n'] += 1

        processed = worker.drain(progress_callback=_tick)
        assert counter['n'] == processed

    def test_drain_returns_zero_when_no_tasks(self, engine):
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor(), concurrency=2)
        assert worker.drain() == 0


class _FullExtractor:
    """Extractor that implements extract_full — returns entities + relationships in one call."""

    def __init__(self):
        self.extract_calls = 0
        self.extract_full_calls = 0

    def extract(self, text: str, entity_types: list[str]) -> list[ExtractedEntity]:
        self.extract_calls += 1
        return [ExtractedEntity(name='Alice', entity_type='person', score=0.9)]

    def extract_full(self, text: str) -> ExtractionResult:
        self.extract_full_calls += 1
        return ExtractionResult(
            entry_type='observation',
            confidence=0.8,
            relevance=0.7,
            entities=[
                ExtractedEntity(name='Alice', entity_type='person', score=0.9),
                ExtractedEntity(name='Acme', entity_type='organization', score=0.9),
            ],
            relationships=[
                ExtractedRelationship(
                    source='Alice', target='Acme', relation_type='works_at', fact='Alice at Acme'
                )
            ],
        )


class TestWorkerFoldedExtraction:
    """When the extractor exposes extract_full, relationships should be applied inline
    and no follow-up link_graph_v3 task should be enqueued."""

    def test_extract_full_used_when_available(self, engine):
        extractor = _FullExtractor()
        worker = BackgroundWorker(engine=engine, extractor=extractor, llm=MockLLM())
        engine.enqueue_task(
            task_type='extract_entities_v3', payload={'entry_id': 'e1'}
        )
        worker.process_one()

        assert extractor.extract_full_calls == 1
        assert extractor.extract_calls == 0

    def test_no_link_graph_enqueued_when_extract_full_available(self, engine):
        extractor = _FullExtractor()
        worker = BackgroundWorker(engine=engine, extractor=extractor, llm=MockLLM())
        engine.enqueue_task(
            task_type='extract_entities_v3', payload={'entry_id': 'e1'}
        )
        worker.process_one()
        # Queue should be empty — no link_graph_v3 follow-up
        assert engine.get_pending_task_count() == 0

    def test_relationships_applied_from_extract_full(self, engine):
        extractor = _FullExtractor()
        worker = BackgroundWorker(engine=engine, extractor=extractor, llm=MockLLM())
        engine.enqueue_task(
            task_type='extract_entities_v3', payload={'entry_id': 'e1'}
        )
        worker.process_one()

        alice_matches = engine.find_entities_by_name('Alice')
        assert len(alice_matches) == 1
        rels = engine.get_relationships_for_entity(alice_matches[0].entity_id)
        assert len(rels) >= 1
        relation_types = {r.relation_type for r in rels}
        assert 'works_at' in relation_types

    def test_legacy_path_preserved_without_extract_full(self, engine):
        """MockExtractor has only extract() — legacy enqueue path must still work."""
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            llm=MockLLM(),
        )
        engine.enqueue_task(
            task_type='extract_entities_v3', payload={'entry_id': 'e1'}
        )
        worker.process_one()
        # Legacy path enqueues link_graph_v3 when ≥2 entities and llm is present
        task = engine.dequeue_task()
        assert task is not None
        assert task[1] == 'link_graph_v3'


class TestWorkerLifecycle:
    """Worker thread start/stop lifecycle."""

    def test_start_and_stop(self, engine):
        worker = BackgroundWorker(engine=engine, extractor=MockExtractor())
        worker.start()
        assert worker._thread is not None
        assert worker._thread.is_alive()
        worker.stop()

    def test_background_processes_task(self, engine):
        engine.enqueue_task(
            task_type='extract_entities_v3',
            payload={'entry_id': 'e1'},
        )
        worker = BackgroundWorker(
            engine=engine,
            extractor=MockExtractor(),
            poll_interval=0.05,
        )
        worker.start()
        time.sleep(0.5)  # give worker time to process
        worker.stop()
        # Verify entities were created
        entity_ids = engine.get_entity_ids_for_entry('e1')
        assert len(entity_ids) >= 1
