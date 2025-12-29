from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.services.monitoring_history import build_and_persist_monitoring_snapshot


logger = logging.getLogger(__name__)


class MonitoringScheduler:
    """Background scheduler for periodic monitoring snapshots.

    Runs entirely inside the backend container process and is intended
    to be controlled from FastAPI startup/shutdown events.
    """

    def __init__(self, interval_minutes: int = 15) -> None:
        self._interval_minutes = interval_minutes
        self._scheduler: Optional[BackgroundScheduler] = None

        # PostgreSQL advisory lock state (single-instance scheduler guard).
        # NOTE: lock key is a fixed BIGINT shared across all backend instances.
        self._lock_key: int = 9_223_372_036_854_770_001
        self._lock_connection = None

    def start(self) -> None:
        """Start the APScheduler instance if not already running.

        This method is idempotent within a single process and will log
        if a running scheduler is already present.
        """
        # Feature flag: allow turning scheduler off completely via env.
        enabled_raw = os.getenv("MONITORING_SCHEDULER_ENABLED", "true").lower()
        if enabled_raw not in ("1", "true", "yes", "on"):
            logger.warning(
                "MonitoringScheduler disabled via MONITORING_SCHEDULER_ENABLED=%s",
                enabled_raw,
            )
            return

        if self._scheduler is not None and self._scheduler.running:
            logger.warning("MonitoringScheduler already running, skipping start")
            return

        # Acquire PostgreSQL advisory lock to ensure only one backend instance
        # runs the scheduler at a time.
        if not self._acquire_advisory_lock():
            logger.warning(
                "MonitoringScheduler disabled (PostgreSQL advisory lock not acquired)"
            )
            return

        scheduler = BackgroundScheduler(timezone="UTC")

        scheduler.add_job(
            self._run_snapshot_job,
            trigger=IntervalTrigger(minutes=self._interval_minutes),
            id="monitoring_snapshot_job",
            replace_existing=True,
            max_instances=1,
            next_run_time=datetime.now(timezone.utc),
        )

        scheduler.start()
        self._scheduler = scheduler
        logger.warning(
            "MonitoringScheduler started with interval %s minutes", self._interval_minutes
        )

    def shutdown(self) -> None:
        """Shutdown the scheduler if it is running."""
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
                logger.warning("MonitoringScheduler stopped")
            finally:
                self._scheduler = None

        # Release advisory lock if held.
        self._release_advisory_lock()

    def _acquire_advisory_lock(self) -> bool:
        """Try to acquire a global PostgreSQL advisory lock.

        The lock is held for the lifetime of this scheduler instance and
        ensures that only one backend process runs the monitoring job.
        """

        if self._lock_connection is not None:
            # Lock is already held in this process.
            return True

        conn = None
        try:
            conn = engine.raw_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s);", (self._lock_key,))
            row = cursor.fetchone()
            acquired = bool(row[0]) if row is not None else False
            cursor.close()

            if not acquired:
                try:
                    conn.rollback()
                except Exception:
                    pass
                conn.close()
                return False

            conn.commit()
            self._lock_connection = conn
            logger.warning(
                "MonitoringScheduler advisory lock acquired (key=%s)",
                self._lock_key,
            )
            return True
        except Exception:
            logger.exception("Failed to acquire PostgreSQL advisory lock")
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            return False

    def _release_advisory_lock(self) -> None:
        """Release the PostgreSQL advisory lock if it is currently held."""

        if self._lock_connection is None:
            return

        try:
            cursor = self._lock_connection.cursor()
            cursor.execute("SELECT pg_advisory_unlock(%s);", (self._lock_key,))
            self._lock_connection.commit()
            cursor.close()
            logger.warning(
                "MonitoringScheduler advisory lock released (key=%s)",
                self._lock_key,
            )
        except Exception:
            # Even if unlock fails, closing the connection will release the lock.
            logger.exception("Failed to release PostgreSQL advisory lock explicitly")
        finally:
            try:
                self._lock_connection.close()
            except Exception:
                pass
            self._lock_connection = None

    @staticmethod
    def _run_snapshot_job() -> None:
        """Job function that builds and persists a monitoring snapshot.

        All exceptions are caught and logged so that failures do not
        bring down the application process.
        """
        logger.warning("Monitoring snapshot job started")
        db: Session = SessionLocal()
        try:
            build_and_persist_monitoring_snapshot(db=db)
            logger.warning("Monitoring snapshot job completed successfully")
        except Exception:
            logger.exception("Error while running monitoring snapshot job")
        finally:
            db.close()
