"""sf6 Task 4 — verify sf4's auto-consolidation trigger fires end-to-end (Seam D→F).

sf4 wired CaptureDrain to call store.consolidate() once the records-since-consolidation
counter crosses consolidation_interval_records (drain.py:137-147). sf6 locks that wiring:
push interval-many records through the drain and assert consolidate() ran. If it does NOT
fire on the integrated base, STOP and fix in capture/* (sf4 lane) — do not paper over it.
"""

from aingram.capture.config import CaptureConfig
from aingram.capture.drain import CaptureDrain
from aingram.capture.queue import CaptureQueue
from aingram.capture.types import CaptureRecord
from aingram.store import MemoryStore
from tests.conftest import MockEmbedder


def _record(**ov):
    d = dict(
        source_tool='claude_code',
        session_id='s1',
        user_prompt='What is RRF?',
        assistant_response='Reciprocal rank fusion.',
        timestamp=1000.0,
        container_tag='aingram:unified',
    )
    d.update(ov)
    return CaptureRecord(**d)


def test_interval_crossing_fires_one_consolidation(tmp_path, monkeypatch):
    calls = []
    original = MemoryStore.consolidate

    def spy(self, **kw):
        calls.append(1)
        return original(self, **kw)

    monkeypatch.setattr(MemoryStore, 'consolidate', spy)

    queue = CaptureQueue(str(tmp_path / 'queue.db'))
    # distinct content so neither is deduped — both count toward the interval
    queue.insert(_record(user_prompt='first distinct question about widgets'))
    queue.insert(_record(user_prompt='second distinct question about gadgets'))
    drain = CaptureDrain(
        queue=queue,
        memory_db_path=str(tmp_path / 'memory.db'),
        config=CaptureConfig(drain_batch_size=10, consolidation_interval_records=2),
        embedder=MockEmbedder(),
    )
    drain.process_batch()
    drain.close()

    assert len(calls) >= 1  # the interval crossing fired consolidation (Seam D→F)
