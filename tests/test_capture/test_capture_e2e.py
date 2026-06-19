# End-to-end honesty check (Seam A DoD): a real mixed batch traverses
# queue -> drain -> gate -> store -> recall. The clean capture lands pending,
# stamped, and retrievable (quarantined, not trusted); the secret capture in
# the same batch is blocked and never stored. No mocks.
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
        user_prompt='use shift=3.0 for ACE-Step',
        assistant_response='noted.',
        timestamp=1000.0,
        container_tag='aingram:unified',
    )
    d.update(ov)
    return CaptureRecord(**d)


def test_autonomous_batch_quarantines_clean_and_blocks_secret(tmp_path):
    queue = CaptureQueue(str(tmp_path / 'queue.db'))
    queue.insert(_record())  # clean
    queue.insert(
        _record(  # secret-bearing, distinct timestamp/prompt
            user_prompt='leak the key',
            assistant_response='export R2_SECRET_ACCESS_KEY=' + 'A' * 48,
            timestamp=1001.0,
        )
    )
    drain = CaptureDrain(
        queue=queue,
        memory_db_path=str(tmp_path / 'memory.db'),
        config=CaptureConfig(drain_batch_size=10),
        embedder=MockEmbedder(),
    )
    drain.process_batch()
    drain.close()

    store = MemoryStore(str(tmp_path / 'memory.db'), embedder=MockEmbedder())
    # The secret was blocked, so exactly the one clean capture is stored.
    assert store.unconsolidated_count() == 1

    results = store.recall('shift', limit=10, verify=False)
    assert len(results) >= 1                 # quarantined != dropped; still recallable
    e = results[0].entry
    assert e.status == 'pending'             # Seam A: quarantine-by-default
    assert e.status != 'approved'            # never auto-approved for an autonomous source
    assert e.source == 'claude_code'         # provenance stamped
    assert e.trust_score is not None         # baseline trust written
    store.close()

    # both queue records were processed (none left pending/stuck)
    assert queue.pending_count() == 0
