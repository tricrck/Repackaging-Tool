"""
Audio download services.

Supports:
- YouTube and most direct media links via yt-dlp.
- Spotify tracks via spotdl if installed; otherwise a clear error.

Spotify note: spotdl is the cleanest Spotify->MP3 path (it matches Spotify
metadata against YouTube and downloads from there). Not in requirements.txt
by default because its dep tree is heavy; install on demand with
`pip install spotdl` if you need Spotify support.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


SPOTIFY_TRACK_RE = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]+)")
ProgressCB = Optional[Callable[[str, str], None]]


def _latest_file(directory: Path, pattern: str) -> Optional[Path]:
    matches = list(directory.glob(pattern))
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def download_audio(url: str, output_dir: str | Path, *, progress_cb: ProgressCB = None) -> Path:
    """
    Download audio from a URL. Returns the path to the MP3.
    Raises RuntimeError on failure, ValueError on empty input.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = url.strip()
    if not url:
        raise ValueError("empty URL")

    if SPOTIFY_TRACK_RE.search(url):
        return _download_spotify(url, output_dir, progress_cb=progress_cb)
    return _download_ytdlp(url, output_dir, progress_cb=progress_cb)


def _download_ytdlp(url: str, output_dir: Path, *, progress_cb: ProgressCB) -> Path:
    """yt-dlp audio extraction."""
    output_template = str(output_dir / "%(title).80B.%(ext)s")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "-o", output_template,
        url,
    ]

    logger.info("yt-dlp: %s", " ".join(cmd))
    if progress_cb:
        progress_cb("audio_download", "Fetching audio")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr or result.stdout}")

    audio = _latest_file(output_dir, "*.mp3") or _latest_file(output_dir, "*.m4a")
    if not audio:
        raise RuntimeError("yt-dlp completed but no audio file was produced")
    return audio


def _download_spotify(url: str, output_dir: Path, *, progress_cb: ProgressCB) -> Path:
    """Spotify via spotdl if installed; otherwise error."""
    if not shutil.which("spotdl"):
        raise RuntimeError(
            "Spotify URL detected but the 'spotdl' CLI is not installed. "
            "Install with: pip install spotdl  (or paste a YouTube link instead)."
        )
    if progress_cb:
        progress_cb("audio_download", "Downloading Spotify track via spotdl")
    cmd = ["spotdl", url, "--output", str(output_dir), "--format", "mp3"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"spotdl failed: {result.stderr or result.stdout}")
    audio = _latest_file(output_dir, "*.mp3")
    if not audio:
        raise RuntimeError("spotdl ran but no MP3 was produced")
    return audio