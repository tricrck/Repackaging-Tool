"""
Pipeline runner: orchestrates audio download + video transform,
updating the VideoProject row as it goes.

Designed to run inside a background thread (see projects.tasks).
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.utils import timezone

from ..models import VideoProject
from .audio import download_audio
from .transform import TransformParams, transform_video

logger = logging.getLogger(__name__)


def _progress_cb(project: VideoProject):
    """Build a closure that updates the project's progress + log fields."""
    lock = threading.Lock()

    def cb(stage: str, label: str, percent: int) -> None:
        with lock:
            project.current_stage = label
            project.progress = max(project.progress, int(percent))
            project.save(update_fields=["current_stage", "progress", "updated_at"])
        logger.info("[project %s] %s — %s%%", project.pk, stage, percent)
        project.append_log(f"{label} ({percent}%)")

    return cb


def run_project(project_id: int) -> None:
    """Top-level pipeline entry point. Safe to call from a thread."""
    try:
        project = VideoProject.objects.get(pk=project_id)
    except VideoProject.DoesNotExist:
        logger.error("run_project: project %s not found", project_id)
        return

    project.status = "running"
    project.progress = 0
    project.error_message = ""
    project.started_at = timezone.now()
    project.save(update_fields=["status", "progress", "error_message", "started_at", "updated_at"])
    project.append_log(f"Started project #{project.pk}")

    try:
        _run(project)
    except Exception as exc:  # noqa: BLE001
        logger.exception("project %s failed", project_id)
        project.status = "failed"
        project.error_message = f"{type(exc).__name__}: {exc}"
        project.append_log(f"FAILED: {exc}")
        project.save(update_fields=["status", "error_message", "updated_at"])
        return

    project.status = "done"
    project.completed_at = timezone.now()
    project.progress = 100
    project.append_log("Pipeline complete")
    project.save(update_fields=[
        "status", "completed_at", "progress", "output", "output_filename",
        "output_size_bytes", "updated_at",
    ])


def _run(project: VideoProject) -> None:
    progress = _progress_cb(project)

    # 1. Resolve background audio
    audio_path: Optional[Path] = None
    if project.song_file:
        audio_path = Path(project.song_file.path)
        progress("audio_resolved", "Using uploaded audio file", 10)
    elif project.song_url:
        audio_dir = Path(settings.MEDIA_ROOT) / "audio" / str(project.pk)
        audio_dir.mkdir(parents=True, exist_ok=True)
        progress("audio_download", f"Downloading audio from {project.song_url[:60]}", 12)
        audio_path = download_audio(project.song_url, audio_dir)
        # Save the audio path onto the project so the user can re-run later
        rel = audio_path.relative_to(settings.MEDIA_ROOT)
        project.song_file.name = str(rel).replace("\\", "/")
        project.save(update_fields=["song_file", "updated_at"])
        progress("audio_resolved", f"Audio ready: {audio_path.name}", 20)

    # 2. Build transform params
    params = TransformParams(
        aspect_ratio=project.aspect_ratio,
        pad_color=project.pad_color,
        codec=project.codec,
        fps=project.fps,
        bitrate=project.bitrate,
        max_duration=project.max_duration,
        ken_burns=project.ken_burns,
        music_volume=project.music_volume,
        original_audio_volume=project.original_audio_volume,
    )

    # 3. Output path
    out_dir = Path(settings.MEDIA_ROOT) / "outputs" / str(project.pk)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"repackaged_{uuid.uuid4().hex[:8]}.mp4"
    out_path = out_dir / out_name

    # 4. Run the transform
    transform_video(
        input_path=project.original.path,
        output_path=out_path,
        params=params,
        audio_path=audio_path,
        progress_cb=progress,
    )

    # 5. Save output reference
    rel_out = out_path.relative_to(settings.MEDIA_ROOT)
    project.output.name = str(rel_out).replace("\\", "/")
    project.output_filename = out_name
    project.output_size_bytes = out_path.stat().st_size