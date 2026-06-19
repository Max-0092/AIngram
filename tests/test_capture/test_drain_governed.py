# The drain must route every record through the gate: clean captures land
# stamped (source + baseline trust) and quarantined (pending); a secret-bearing
# capture is blocked entirely (marked error, never stored).
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


def _drain(tmp_path, queue):
    return CaptureDrain(
        queue=queue,
        memory_db_path=str(tmp_path / 'memory.db'),
        config=CaptureConfig(drain_batch_size=10),
        embedder=MockEmbedder(),
    )


def test_drained_autonomous_capture_lands_pending_with_governance(tmp_path):
    queue = CaptureQueue(str(tmp_path / 'queue.db'))
    queue.insert(_record())
    drain = _drain(tmp_path, queue)
    assert drain.process_batch() == 1
    drain.close()

    store = MemoryStore(str(tmp_path / 'memory.db'), embedder=MockEmbedder())
    results = store.recall('RRF', limit=5, verify=False)
    assert len(results) >= 1
    e = results[0].entry
    assert e.status == 'pending'          # quarantine-by-default (never approved)
    assert e.source == 'claude_code'      # provenance stamped by the gate (NULL without it)
    assert e.trust_score is not None      # baseline trust written (NULL without it)
    store.close()


def test_drained_secret_is_blocked_not_stored(tmp_path):
    queue = CaptureQueue(str(tmp_path / 'queue.db'))
    queue.insert(
        _record(
            user_prompt='here is the key',
            assistant_response='export R2_SECRET_ACCESS_KEY=' + 'A' * 48,
        )
    )
    drain = _drain(tmp_path, queue)
    drain.process_batch()
    drain.close()

    store = MemoryStore(str(tmp_path / 'memory.db'), embedder=MockEmbedder())
    assert store.unconsolidated_count() == 0   # secret capture never stored
    store.close()
    # the record was processed (marked error), not left pending/stuck
    assert queue.pending_count() == 0
