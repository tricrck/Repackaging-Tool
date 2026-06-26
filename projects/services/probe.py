"""
ffprobe wrapper for input video metadata.

Used to populate duration_seconds / width / height on the VideoProject row
right after upload, so the detail page can show "3:21, 1920×1080" and the
form can warn on aspect-ratio mismatches before the pipeline runs.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class VideoInfo(TypedDict):
    duration: float       # seconds, 0.0 if unknown
    width: int
    height: int
    has_audio: bool
    container: str        # e.g. "mov,mp4,m4a,3gp,3g2,mj2"
    vcodec: str           # "" if no video stream
    acodec: str           # "" if no audio stream


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe(path: str | Path) -> Optional[VideoInfo]:
    """
    Return VideoInfo for `path` or None on failure.

    Failure is non-fatal: callers should treat None as "we don't know" and
    leave the corresponding fields blank. The pipeline still runs; we just
    lose the ability to show nice metadata in the UI.
    """
    if not ffprobe_available():
        logger.warning("ffprobe not on PATH; skipping probe for %s", path)
        return None

    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out for %s", path)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return None

    if result.returncode != 0:
        logger.warning("ffprobe non-zero exit for %s: %s", path, result.stderr[:200])
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    if v_stream and v_stream.get("duration"):
        try:
            duration = float(v_stream["duration"])
        except (TypeError, ValueError):
            pass
    if not duration and fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            pass

    width = 0
    height = 0
    if v_stream:
        try:
            width = int(v_stream.get("width") or 0)
            height = int(v_stream.get("height") or 0)
        except (TypeError, ValueError):
            pass

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        has_audio=a_stream is not None,
        container=(fmt.get("format_name") or "").split(",")[0],
        vcodec=(v_stream or {}).get("codec_name", "") or "",
        acodec=(a_stream or {}).get("codec_name", "") or "",
    )


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as M:SS or H:MM:SS."""
    if seconds <= 0:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
