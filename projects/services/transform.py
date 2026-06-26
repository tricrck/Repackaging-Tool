"""
Video transformation pipeline.

Operations (all optional):
- Trim to a start/end window (or to a max duration).
- Resize / pad to target aspect ratio (9:16, 16:9, 1:1, 4:5, or keep source).
- Mix background music with original audio at configurable volumes.
- Apply Ken Burns pan/zoom (useful for image slideshows).
- Re-encode with chosen codec, fps, bitrate, with real per-block progress
  forwarded via the ffmpeg `-progress pipe:1` runner.

This is a normal creator repackaging pipeline. There is intentionally no
watermark removal, no perceptual-hash-noise, no QR/code obfuscation, and no
detection-evasion transforms.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .ffmpeg_runner import encode_with_progress

logger = logging.getLogger(__name__)

# Importing moviepy lazily because importing it at module load time on a
# cold process takes ~1-2s; defer until we actually need it.
VideoFileClip = None
AudioFileClip = None
CompositeAudioClip = None


def _ensure_moviepy():
    global VideoFileClip, AudioFileClip, CompositeAudioClip
    if VideoFileClip is None:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip  # type: ignore
    return VideoFileClip, AudioFileClip, CompositeAudioClip


# progress_cb signatures:
#   (stage, label, percent) — coarse stage transitions
#   (stage, label, percent, sub) — fine sub-stage percent (e.g. encode block percent)
ProgressCB = Optional[Callable[..., None]]


@dataclass
class TransformParams:
    aspect_ratio: str = "9:16"     # 'source' or one of '9:16', '16:9', '1:1', '4:5'
    pad_color: str = "#000000"     # hex colour for padding bars
    codec: str = "libx264"
    fps: int = 30
    bitrate: str = "2M"
    max_duration: int = 0          # 0 = keep full duration
    start_seconds: float = 0.0     # trim start (0 = from beginning)
    end_seconds: float = 0.0       # trim end   (0 = until end of clip)
    ken_burns: bool = False
    music_volume: float = 0.8
    original_audio_volume: float = 0.2


def hex_to_rgb(hexstr: str) -> tuple[int, int, int]:
    s = hexstr.lstrip("#")
    if len(s) != 6:
        return (0, 0, 0)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


# Aspect-ratio target dimensions (height-anchored for portrait, width-anchored otherwise)
_TARGETS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1":  (1080, 1080),
    "4:5":  (1080, 1350),
}


def _resize_and_pad(clip, target_w: int, target_h: int, pad_rgb: tuple[int, int, int]):
    """Resize clip to fit inside (target_w, target_h), preserving aspect, then pad."""
    src_ratio = clip.w / clip.h
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        new_w = target_w
        new_h = int(round(target_w / src_ratio))
    else:
        new_h = target_h
        new_w = int(round(target_h * src_ratio))

    new_w -= new_w % 2
    new_h -= new_h % 2

    resized = clip.resized((new_w, new_h))

    pad_left = (target_w - new_w) // 2
    pad_right = target_w - new_w - pad_left
    pad_top = (target_h - new_h) // 2
    pad_bottom = target_h - new_h - pad_top

    if pad_left or pad_right or pad_top or pad_bottom:
        from moviepy.video.VideoClip import ColorClip  # type: ignore
        from moviepy import CompositeVideoClip  # type: ignore
        canvas = ColorClip(size=(target_w, target_h), color=pad_rgb, duration=clip.duration)
        canvas = canvas.with_position(("center", "center")).with_duration(clip.duration)
        return CompositeVideoClip(
            [canvas, resized.with_position(("center", "center"))],
            size=(target_w, target_h),
        ).with_duration(clip.duration)
    return resized


def _ken_burns(clip):
    """Slow zoom-in from 1.00 to 1.04 over the clip duration."""
    duration = clip.duration

    def filter(get_frame, t):
        frame = get_frame(t)
        if duration <= 0:
            return frame
        zoom = 1.0 + 0.04 * (t / duration)
        h, w = frame.shape[:2]
        new_w, new_h = int(w * zoom), int(h * zoom)
        import cv2
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        x1 = (new_w - w) // 2
        y1 = (new_h - h) // 2
        return resized[y1:y1 + h, x1:x1 + w]

    return clip.transform(filter)


def _emit(progress_cb, stage: str, label: str, percent: int) -> None:
    if progress_cb:
        try:
            progress_cb(stage, label, percent)
        except TypeError:
            # Old single-arg callback (e.g. tests). Ignore.
            pass


def transform_video(
    input_path: str | Path,
    output_path: str | Path,
    params: TransformParams,
    audio_path: Optional[str | Path] = None,
    *,
    progress_cb: ProgressCB = None,
) -> Path:
    """
    Run the transform pipeline. Writes the final MP4 to `output_path`.
    Returns the output path.
    """
    VideoFileClip, AudioFileClip, CompositeAudioClip = _ensure_moviepy()
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _emit(progress_cb, "load", "Loading source video", 5)

    clip = VideoFileClip(str(input_path))
    try:
        # 1. Trim window
        if params.start_seconds and params.start_seconds > 0:
            start = min(params.start_seconds, max(0, clip.duration - 0.05))
        else:
            start = 0.0
        if params.end_seconds and params.end_seconds > 0:
            end = min(params.end_seconds, clip.duration)
        else:
            end = clip.duration
        if end > start:
            clip = clip.subclipped(start, end)
        if start or (params.end_seconds and params.end_seconds > 0):
            _emit(progress_cb, "trim", f"Trimmed {start:.2f}s–{end:.2f}s", 12)

        # 2. max_duration caps the trimmed window
        if params.max_duration and params.max_duration > 0 and clip.duration > params.max_duration:
            clip = clip.subclipped(0, params.max_duration)
            _emit(progress_cb, "trim", f"Clipped to {params.max_duration}s", 15)

        # 3. Aspect-ratio resize/pad
        if params.aspect_ratio in _TARGETS:
            tw, th = _TARGETS[params.aspect_ratio]
            pad_rgb = hex_to_rgb(params.pad_color)
            clip = _resize_and_pad(clip, tw, th, pad_rgb)
            _emit(progress_cb, "resize", f"Resized to {params.aspect_ratio}", 25)

        # 4. Ken Burns
        if params.ken_burns:
            clip = _ken_burns(clip)
            _emit(progress_cb, "ken_burns", "Applied Ken Burns pan/zoom", 35)

        # 5. Audio
        has_audio_in_output = False
        if audio_path and Path(audio_path).exists():
            music = AudioFileClip(str(audio_path))
            if music.duration < clip.duration:
                try:
                    music = music.loop(duration=clip.duration)  # type: ignore[attr-defined]
                except AttributeError:
                    music = music.with_duration(clip.duration)
            else:
                music = music.subclipped(0, clip.duration)
            music = music.with_volume_scaled(params.music_volume)
            components = [music]
            if clip.audio is not None:
                components.append(clip.audio.with_volume_scaled(params.original_audio_volume))
            clip = clip.with_audio(CompositeAudioClip(components))
            has_audio_in_output = True
            _emit(progress_cb, "audio_mix", "Mixed background music", 50)
        elif clip.audio is not None:
            clip = clip.with_audio(clip.audio.with_volume_scaled(params.original_audio_volume))
            has_audio_in_output = True

        # 6. Moviepy encode → intermediate file
        _emit(progress_cb, "encode_prep", f"Preparing encode ({params.codec} @ {params.fps}fps)", 60)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            clip.write_videofile(
                str(tmp_path),
                codec=params.codec if params.codec != "libvpx-vp9" else "libvpx-vp9",
                audio_codec="aac",
                fps=params.fps,
                bitrate=params.bitrate,
                preset="medium",
                logger=None,
            )

            # 7. Final pass: real progress from ffmpeg -progress pipe:1
            _emit(progress_cb, "encode", f"Encoding with {params.codec} @ {params.fps}fps", 65)

            # Build a per-block progress callback that maps 0..100 from
            # ffmpeg onto the 65..95 slice of our overall bar.
            def ffmpeg_progress(pct: int) -> None:
                # pct is 0..100 from ffmpeg; map to 65..95 of the overall bar
                overall = 65 + int(pct * 0.30)
                _emit(progress_cb, "encode", f"Encoding {pct}%", overall)

            ok = encode_with_progress(
                input_path=tmp_path,
                output_path=output_path,
                codec=params.codec,
                fps=params.fps,
                bitrate=params.bitrate,
                width=clip.w,
                height=clip.h,
                duration_seconds=clip.duration,
                has_audio=has_audio_in_output,
                progress_cb=ffmpeg_progress,
            )
            if not ok:
                logger.warning("ffmpeg progress pass failed; falling back to direct copy")
                shutil.copy2(str(tmp_path), str(output_path))
                _emit(progress_cb, "container", "Re-muxed (fallback copy)", 95)
            else:
                _emit(progress_cb, "container", "Finalised MP4 container", 95)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        _emit(progress_cb, "done", "Finished", 100)
        return output_path
    finally:
        clip.close()
