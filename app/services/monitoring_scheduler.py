from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
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

    def start(self) -> None:
        """Start the APScheduler instance if not already running.

        This method is idempotent within a single process and will log
        if a running scheduler is already present.
        """
        if self._scheduler is not None and self._scheduler.running:
            logger.warning("MonitoringScheduler already running, skipping start")
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
