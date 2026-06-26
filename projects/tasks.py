"""
Background task dispatcher.

This app runs the video pipeline in a daemon thread instead of pulling in
Celery / Redis. For local / single-user use this is plenty; for production
swap in Celery by replacing `start_in_thread` with a `.delay()` call.
"""
from __future__ import annotations

import logging
import threading

from .services.pipeline import run_project

logger = logging.getLogger(__name__)


def start_in_thread(project_id: int) -> None:
    """Kick off the pipeline in a background thread and return immediately."""
    t = threading.Thread(
        target=_safe_run,
        args=(project_id,),
        name=f"pipeline-{project_id}",
        daemon=True,
    )
    t.start()


def _safe_run(project_id: int) -> None:
    try:
        run_project(project_id)
    except Exception:  # noqa: BLE001
        logger.exception("pipeline thread crashed for project %s", project_id)