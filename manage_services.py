#!/usr/bin/env python
"""
Quick CLI runner: process a single video without going through the web UI.

Usage:
  python manage_services.py --input path/to/video.mp4 \
                            --audio-url "https://..." \
                            --aspect-ratio 9:16 \
                            --output out.mp4

Useful for testing the pipeline or batch-processing from a script.
"""
import argparse
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--audio-url", default="")
    p.add_argument("--audio-file", default="")
    p.add_argument("--aspect-ratio", default="9:16", choices=["source", "9:16", "16:9", "1:1", "4:5"])
    p.add_argument("--codec", default="libx264", choices=["libx264", "libx265", "libvpx-vp9"])
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--bitrate", default="2M")
    p.add_argument("--max-duration", type=int, default=0)
    p.add_argument("--ken-burns", action="store_true")
    p.add_argument("--music-volume", type=float, default=0.8)
    p.add_argument("--original-volume", type=float, default=0.2)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    # Bootstrap Django settings so the services can import them.
    sys.path.insert(0, str(Path(__file__).parent))
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "repackage.settings")
    import django
    django.setup()

    from projects.services.audio import download_audio
    from projects.services.transform import TransformParams, transform_video

    audio_path = None
    if args.audio_file:
        audio_path = Path(args.audio_file)
    elif args.audio_url:
        out_dir = Path(args.output).parent / "_audio"
        print(f"[audio] downloading from {args.audio_url} → {out_dir}")
        audio_path = download_audio(args.audio_url, out_dir)
        print(f"[audio] {audio_path}")

    params = TransformParams(
        aspect_ratio=args.aspect_ratio,
        codec=args.codec,
        fps=args.fps,
        bitrate=args.bitrate,
        max_duration=args.max_duration,
        ken_burns=args.ken_burns,
        music_volume=args.music_volume,
        original_audio_volume=args.original_volume,
    )

    def cb(stage, label, pct):
        print(f"[{pct:3d}%] {stage}: {label}", flush=True)

    t0 = time.time()
    out = transform_video(args.input, args.output, params, audio_path, progress_cb=cb)
    print(f"\nDone in {time.time()-t0:.1f}s → {out}")


if __name__ == "__main__":
    main()