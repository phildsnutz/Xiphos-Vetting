"""
Background Neo4j sync job manager.

Queues long-running full sync work off the request thread while persisting job
state in the main Helios database.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

import db
from neo4j_integration import full_sync_from_postgres, incremental_sync


logger = logging.getLogger(__name__)


class Neo4jSyncScheduler:
    """Single-flight async scheduler for Neo4j sync jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_threads: dict[str, threading.Thread] = {}

    def queue_full_sync(
        self,
        *,
        requested_by: str = "",
        requested_by_email: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._queue_job(
            sync_kind="full",
            since_timestamp="",
            requested_by=requested_by,
            requested_by_email=requested_by_email,
            metadata=metadata,
        )

    def queue_incremental_sync(
        self,
        since_timestamp: str,
        *,
        requested_by: str = "",
        requested_by_email: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._queue_job(
            sync_kind="incremental",
            since_timestamp=since_timestamp,
            requested_by=requested_by,
            requested_by_email=requested_by_email,
            metadata=metadata,
        )

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        return db.get_neo4j_sync_job(job_id)

    def get_latest_status(self) -> dict[str, Any] | None:
        return db.get_latest_neo4j_sync_job()

    def _queue_job(
        self,
        *,
        sync_kind: str,
        since_timestamp: str,
        requested_by: str,
        requested_by_email: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._lock:
            active = db.get_active_neo4j_sync_job()
            if active:
                active["reused_existing_job"] = True
                return active

            job_id = str(uuid.uuid4())
            db.create_neo4j_sync_job(
                job_id,
                sync_kind=sync_kind,
                since_timestamp=since_timestamp,
                requested_by=requested_by,
                requested_by_email=requested_by_email,
                metadata=metadata,
                status="queued",
            )
            thread = threading.Thread(
                target=self._execute_job,
                args=(job_id, sync_kind, since_timestamp),
                daemon=True,
            )
            self._active_threads[job_id] = thread
            thread.start()
            job = db.get_neo4j_sync_job(job_id) or {"job_id": job_id, "status": "queued"}
            job["reused_existing_job"] = False
            return job

    def _execute_job(self, job_id: str, sync_kind: str, since_timestamp: str) -> None:
        started = time.time()
        db.start_neo4j_sync_job(job_id)
        try:
            if sync_kind == "incremental":
                result = incremental_sync(since_timestamp)
            else:
                result = full_sync_from_postgres()

            error = str(result.get("error") or "").strip()
            duration_ms = float(result.get("duration_ms") or ((time.time() - started) * 1000))
            metadata = {
                "sync_kind": sync_kind,
                "since_timestamp": since_timestamp or None,
                "status": result.get("status") or ("failed" if error else "success"),
            }
            if error:
                db.fail_neo4j_sync_job(
                    job_id,
                    error=error,
                    duration_ms=duration_ms,
                    metadata=metadata,
                )
                return

            db.complete_neo4j_sync_job(
                job_id,
                entities_synced=int(result.get("entities_synced") or 0),
                relationships_synced=int(result.get("relationships_synced") or 0),
                duration_ms=duration_ms,
                metadata=metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive background protection
            logger.error("Neo4j %s sync job %s failed: %s", sync_kind, job_id, exc, exc_info=True)
            db.fail_neo4j_sync_job(
                job_id,
                error=str(exc),
                duration_ms=(time.time() - started) * 1000,
                metadata={"sync_kind": sync_kind, "since_timestamp": since_timestamp or None, "status": "failed"},
            )
        finally:
            with self._lock:
                self._active_threads.pop(job_id, None)


_scheduler: Neo4jSyncScheduler | None = None
_scheduler_lock = threading.Lock()


def get_neo4j_sync_scheduler() -> Neo4jSyncScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = Neo4jSyncScheduler()
    return _scheduler
