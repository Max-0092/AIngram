from __future__ import annotations

import json
import logging
import threading

from aingram.capture.config import CaptureConfig
from aingram.capture.gate import evaluate_capture
from aingram.capture.queue import CaptureQueue
from aingram.capture.types import CaptureRecord

logger = logging.getLogger(__name__)


class CaptureDrain:
    def __init__(
        self,
        *,
        queue: CaptureQueue,
        config: CaptureConfig,
        store=None,
        memory_db_path: str = '',
        embedder=None,
    ) -> None:
        self._queue = queue
        self._config = config
        self._embedder = embedder
        if store is not None:
            self._store = store
            self._owns_store = False
        else:
            self._store = None
            self._owns_store = True
        self._memory_db_path = memory_db_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # None = not yet initialized; will be seeded from the DB on first batch
        # so that entries accumulated across daemon restarts count toward the interval.
        self._records_since_consolidation: int | None = None

    def _get_store(self):
        if self._store is None:
            from aingram.store import MemoryStore

            self._store = MemoryStore(
                self._memory_db_path,
                agent_name='capture-daemon',
                embedder=self._embedder,
            )
        return self._store

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def close(self) -> None:
        self.stop()
        if self._store is not None and self._owns_store:
            self._store.close()
            self._store = None

    def _run(self) -> None:
        self._startup_consolidation_check()
        while not self._stop.is_set():
            count = self.process_batch()
            if count == 0:
                self._stop.wait(self._config.poll_interval)

    def _startup_consolidation_check(self) -> None:
        """Fire consolidation on startup if the DB already has a backlog."""
        interval = self._config.consolidation_interval_records
        if interval <= 0:
            return
        try:
            existing = self._get_store().unconsolidated_count()
            self._records_since_consolidation = existing
            if existing >= interval:
                logger.info(
                    'Startup: %d unconsolidated entries >= interval %d, running consolidation',
                    existing,
                    interval,
                )
                self._get_store().consolidate()
                self._records_since_consolidation = 0
        except Exception as e:
            logger.error('Startup consolidation check failed: %s', e, exc_info=True)

    def process_batch(self) -> int:
        batch = self._queue.dequeue_batch(self._config.drain_batch_size)
        if not batch:
            return 0

        # Seed counter from the DB on first batch so entries accumulated across
        # daemon restarts count toward the consolidation interval.
        if self._records_since_consolidation is None:
            self._records_since_consolidation = self._get_store().unconsolidated_count()
            logger.debug(
                'Initialized consolidation counter from DB: %d unconsolidated entries',
                self._records_since_consolidation,
            )

        for row_id, record in batch:
            try:
                store = self._get_store()
                content = self._format_for_remember(record)
                decision = evaluate_capture(content, source=record.source_tool)
                if not decision.allow:
                    # Secret-bearing capture: blocked, never stored, not counted.
                    self._queue.mark_error(row_id, decision.reason)
                    continue
                metadata = self._build_metadata(record)
                tags = ['captured', record.source_tool]
                entry_id = store.remember(content, metadata=metadata, tags=tags)
                # Stamp governance: provenance + quarantine status + baseline trust.
                store._engine.set_governance(
                    entry_id,
                    source=decision.source,
                    status=decision.status,
                    trust_score=decision.trust_score,
                )
                self._queue.mark_done(row_id)
                self._records_since_consolidation += 1
            except Exception as e:
                logger.error('Failed to drain record %s: %s', row_id, e, exc_info=True)
                self._queue.mark_error(row_id, str(e))

        if (
            self._config.consolidation_interval_records > 0
            and self._records_since_consolidation is not None
            and self._records_since_consolidation >= self._config.consolidation_interval_records
        ):
            try:
                store = self._get_store()
                store.consolidate()
                self._records_since_consolidation = 0
            except Exception as e:
                logger.error('Auto-consolidation failed: %s', e, exc_info=True)

        return len(batch)

    @staticmethod
    def _format_for_remember(record: CaptureRecord) -> str:
        parts = []
        if record.user_prompt:
            parts.append(record.user_prompt)
        if record.assistant_response:
            parts.append(record.assistant_response)
        return '\n\n---\n\n'.join(parts)

    @staticmethod
    def _build_metadata(record: CaptureRecord) -> dict:
        meta = {
            'source_tool': record.source_tool,
            'capture_session_id': record.session_id,
        }
        if record.container_tag:
            meta['container_tag'] = record.container_tag
        if record.model:
            meta['model'] = record.model
        if record.project_path:
            meta['project_path'] = record.project_path
        if record.metadata:
            try:
                extra = json.loads(record.metadata)
                if isinstance(extra, dict):
                    meta.update(extra)
            except json.JSONDecodeError:
                pass
        return meta
