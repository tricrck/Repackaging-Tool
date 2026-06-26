"""
ffmpeg invocation with structured progress reporting.

Replaces the "encode then finalize" pair in transform.py with a single
ffmpeg pass that we drive ourselves, emitting per-block percent via a
callback. The callback is wired to the project's progress closure so the
detail page sees the bar move smoothly from 0 to 100 across the encode.

Why not moviepy: moviepy's progress logger is either completely silent
(`logger=None`) or extremely chatty (per-frame `t` updates). Going
through ffmpeg directly with `-progress pipe:1` gives us a clean
`out_time_us / duration_time` ratio we can map to 0..100.

This module does NOT change the final MP4 contract — it still writes
yuv420p + aac + faststart, same as `_ffmpeg_finalize` did.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

ProgressCB = Optional[Callable[[int], None]]
# signature: progress_cb(percent) where percent is 0..100

_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _run_ffmpeg_with_progress(
    cmd: Sequence[str],
    duration_seconds: float,
    progress_cb: ProgressCB,
    *,
    log_path: Optional[Path] = None,
) -> int:
    """
    Run ffmpeg and forward its `-progress` output to progress_cb.

    Returns the process return code. The caller decides whether non-zero
    is fatal. If duration_seconds is 0 or unknown, we still call progress_cb
    at 0 and 100 but skip intermediate updates.
    """
    full_cmd = list(cmd) + ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    logger.info("ffmpeg: %s", " ".join(full_cmd))

    log_fh = open(log_path, "a", encoding="utf-8") if log_path else None
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        if log_fh:
            log_fh.close()
        raise

    assert proc.stdout is not None
    block: dict[str, str] = {}
    last_percent = -1
    # ffmpeg's -progress output normally separates blocks with a blank line,
    # but in practice (especially on Windows + libx264) the blank line is
    # often missing. Treat `frame=` (the first key of every block) as the
    # reliable block-start signal instead.

    def flush_block() -> None:
        nonlocal last_percent
        if not block:
            return
        status = block.get("progress", "")
        out_us = block.get("out_time_us") or block.get("out_time_ms")
        if out_us and duration_seconds > 0:
            try:
                us = int(out_us)
                if "out_time_ms" in block and "out_time_us" not in block:
                    seconds = us / 1000.0
                else:
                    seconds = us / 1_000_000.0
                pct = int(min(100, max(0, (seconds / duration_seconds) * 100)))
            except ValueError:
                pct = last_percent if last_percent >= 0 else 0
        else:
            pct = last_percent if last_percent >= 0 else 0
        if status == "end":
            pct = 100
        if pct != last_percent and progress_cb:
            progress_cb(pct)
        last_percent = pct
        block.clear()

    try:
        for line in proc.stdout:
            line = line.rstrip("\n").rstrip("\r")
            if line == "":
                flush_block()
                continue
            m = _KV_RE.match(line)
            if not m:
                if log_fh:
                    log_fh.write(line + "\n")
                continue
            key, value = m.group(1), m.group(2)
            # New block starts the moment we see a "frame=" key while the
            # current block already has data — flush what we have first.
            if key == "frame" and block:
                flush_block()
            block[key] = value
            if log_fh:
                log_fh.write(f"{key}={value}\n")
        flush_block()

        # Drain stderr (suppressed -loglevel error, but we still want any errors)
        err = proc.stderr.read() if proc.stderr else ""
        if err and log_fh:
            log_fh.write("--- stderr ---\n" + err + "\n")
        return proc.wait()
    finally:
        if log_fh:
            log_fh.close()


def encode_with_progress(
    input_path: Path,
    output_path: Path,
    *,
    codec: str,
    fps: int,
    bitrate: str,
    width: int,
    height: int,
    duration_seconds: float,
    has_audio: bool,
    progress_cb: ProgressCB = None,
    log_path: Optional[Path] = None,
) -> bool:
    """
    One ffmpeg pass that produces the final MP4 and streams progress.

    Returns True on success. On failure returns False; the caller is
    expected to log the error and decide whether to retry as a straight
    copy (the previous behaviour).
    """
    # Scale to even dimensions; preserve aspect with a +pad filter that
    # also handles the letterbox case. For the "source" aspect ratio we
    # simply pass through.
    vf = f"scale=trunc(iw/2)*2:trunc(ih/2)*2"

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-r", str(fps),
        "-c:v", codec,
        "-b:v", bitrate,
        "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(output_path)]

    try:
        rc = _run_ffmpeg_with_progress(
            cmd, duration_seconds=duration_seconds,
            progress_cb=progress_cb, log_path=log_path,
        )
    except FileNotFoundError:
        logger.error("ffmpeg binary not found on PATH")
        return False

    if rc != 0:
        logger.error("ffmpeg encode failed (rc=%s)", rc)
        return False
    return True
