# tricxv6 — Video Repackaging Tool

A local Django 5.1 web app that re-encodes a source video to a different aspect
ratio, mixes in background music (from a URL or an uploaded file), and writes
a platform-ready MP4. Bootstrap 5 UI served from CDN, no npm, no Tailwind.

> **What this is.** A creator's repackaging tool — same category of workflow as
> resizing a clip for Reels/Shorts/TikTok or adding a backing track before
> re-uploading. It does **not** implement watermark removal, perceptual-hash
> noise injection, QR/code obfuscation, micro-rotation for hash misalignment,
> frame-splitting, or any other transform whose purpose is to evade a platform's
> content matching / duplicate detection.

---

## Stack

- **Django 5.1** (SQLite, dev defaults)
- **moviepy 2.x** for clip assembly (lazy-imported to keep cold start fast)
- **opencv-python-headless** for the Ken Burns pan/zoom
- **Pillow** for pad-canvas image handling
- **yt-dlp** for YouTube / direct-link audio extraction
- **spotdl** *(optional, on demand)* — only needed for Spotify URLs
- **ffmpeg** — final container pass (`+faststart`, `yuv420p`)
- **Bootstrap 5 + Bootstrap Icons** — jsdelivr CDN, no build step

Full `requirements.txt` is at the repo root and pulls only the always-needed
deps. `spotdl` is commented out with install-on-demand instructions.

---

## Project layout

```
tricxv6/
├── manage.py                       # Django entrypoint
├── manage_services.py              # CLI runner for the same pipeline (no UI)
├── requirements.txt
├── repackage/                      # Django project
│   ├── settings.py                 # Installed apps, media dirs, upload caps
│   ├── urls.py                     # Routes projects/* + admin
│   ├── asgi.py / wsgi.py
│   └── …
├── projects/                       # The single Django app
│   ├── models.py                   # VideoProject row (status, progress, log…)
│   ├── forms.py                    # ProjectForm + Bootstrap widget classes
│   ├── views.py                    # index / list / new / detail / status / download / delete
│   ├── tasks.py                    # start_in_thread() — daemon-thread dispatcher
│   ├── admin.py                    # Readonly-on-progress fields
│   ├── migrations/0001_initial.py
│   └── services/
│       ├── audio.py                # yt-dlp + spotdl wrapper
│       ├── transform.py            # The actual video pipeline
│       └── pipeline.py             # Orchestrator that wires model → services
├── templates/
│   ├── base.html                   # Nav, messages, Bootstrap CDN
│   └── projects/                   # index, list, new, detail
├── media/                          # User uploads, audio cache, outputs
│   ├── uploads/<pk>/…
│   ├── audio/<pk>/…
│   └── outputs/<pk>/…
├── static/                         # Empty (Bootstrap comes from CDN)
└── test_assets/                    # Pre-made test clips used during dev
```

---

## Data model

One table: `projects_videoproject`. Highlights (see `projects/models.py` for
the full list):

| Field | Purpose |
| --- | --- |
| `title`, `original`, `original_filename` | Source clip |
| `song_url` / `song_file` | Background music — exactly one is required for mixing, both blank means "keep original audio only" |
| `music_volume`, `original_audio_volume` | 0.0–1.0 mix |
| `aspect_ratio` | `source`, `9:16`, `16:9`, `1:1`, `4:5` |
| `pad_color` | Hex colour for the letterbox bars |
| `codec` | `libx264`, `libx265`, `libvpx-vp9` |
| `fps`, `bitrate` | Encode params |
| `max_duration` | Trim to N seconds (0 = keep full) |
| `ken_burns` | Slow zoom-in pan, useful for photo slideshows |
| `output`, `output_filename`, `output_size_bytes` | Filled in on success |
| `status` | `draft` → `queued` → `running` → `done` \| `failed` |
| `progress`, `current_stage`, `error_message`, `log` | Live progress state |

`append_log()` timestamps each line and persists it on the row, so the detail
page can replay the pipeline history.

---

## Pipeline

`projects/tasks.py:start_in_thread(pk)` spawns a daemon thread (Celery-shaped
seam — swap to `.delay()` in production). The thread calls
`services.pipeline.run_project(pk)` which:

1. **Resolves audio.** If `song_file` is set, use it directly. Otherwise
   download from `song_url` into `media/audio/<pk>/`. `services/audio.py`
   detects Spotify URLs by regex and routes to `spotdl` if it's on the
   `PATH`; everything else goes through `yt-dlp -x --audio-format mp3`.
2. **Runs `services/transform.py:transform_video()`.** Steps:
   1. Load source via `moviepy.VideoFileClip` (lazy import).
   2. Trim to `max_duration` if set.
   3. Resize + pad to the target aspect ratio (centred, configurable
      `pad_color`, dimensions rounded to even numbers for `yuv420p`).
   4. Optionally apply Ken Burns (`1.0x` → `1.04x` zoom over duration,
      done with `cv2.resize` per frame inside `clip.transform`).
   5. Mix audio: background music + (optionally) original audio at the
      configured volumes via `CompositeAudioClip`. Music that is shorter
      than the clip is looped to fill.
   6. Encode with moviepy (chosen codec, fps, bitrate), then re-mux the
      intermediate file with a final `ffmpeg` pass that enforces
      `yuv420p` and `+faststart`. Falls back to a `shutil.copy2` if the
      ffmpeg finalise fails (e.g. codec not present in the local build).
3. **Persists output reference** (`output`, `output_filename`,
   `output_size_bytes`) and marks the project `done`.

Progress is reported via a thread-safe closure
(`pipeline._progress_cb`) that updates `current_stage`, `progress`, and
appends to the `log` text field. The detail page polls
`/projects/<pk>/status/` every 1.5 s and renders the bar / log live.

---

## Web UI

- **`/`** — Hero + 6 most recent projects, with status badges and a progress
  bar on each card.
- **`/projects/`** — Filterable table of every project (by status).
- **`/projects/new/`** — Two-column form: source + audio on the left,
  output settings (aspect / codec / fps / bitrate / pad colour / max
  duration / Ken Burns) on the right. Range sliders for the two volume
  knobs are wired to a live value label via a tiny inline script.
  Submitting creates the row, marks it `queued`, and dispatches the
  pipeline in a background thread.
- **`/projects/<pk>/`** — Live progress view. Shows stage label, animated
  progress bar, current status badge, key settings in a side panel, the
  raw pipeline log in a `<details>` block, and a download button once the
  output exists. Includes a re-run form (re-queues a finished or failed
  job) and a delete form (cleans up media files best-effort).
- **`/admin/`** — Standard Django admin with read-only progress fields.

The whole UI is one base template (`templates/base.html`) with a fixed
navbar and Bootstrap 5 + Bootstrap Icons pulled from jsdelivr — no Vite,
no webpack, no Tailwind, no static JS bundles of our own.

---

## CLI runner

`manage_services.py` runs the same pipeline as a standalone script (no
HTTP, no database row — writes directly to the path you give it):

```bash
python manage_services.py \
  --input test_assets/source_16x9.mp4 \
  --audio-file test_assets/test_audio.m4a \
  --aspect-ratio 9:16 \
  --ken-burns \
  --output /tmp/out.mp4
```

The `--audio-url` flag goes through the same yt-dlp / spotdl path as the
web form. The CLI is useful for batch processing and for verifying
pipeline changes without standing up the dev server.

---

## Running it

```bash
# 1. Activate the venv (the one shipped in this checkout is .venv/)
source .venv/Scripts/activate   # git-bash on Windows

# 2. Apply migrations (one-time; already done in this checkout)
python manage.py migrate

# 3. Start the dev server
python manage.py runserver

# 4. Open http://127.0.0.1:8000/
```

System requirements: **ffmpeg** must be on `PATH` (used by both moviepy
and the final re-mux). `yt-dlp` is required only if you use the
song-URL feature.

---

## What's intentionally not built

The original design brief included a set of **detection-evasion**
transforms (watermark blurring, perceptual-hash noise, micro-rotation,
QR-code overlay, splitting into sub-threshold segments, codec/fps
shuffling to break fingerprints, …). Those are **not** part of this
implementation — see the TODO section below for the reasoning and for
the list of pieces that would be needed to add any of them.

---

## TODO — parts of the original idea I can't help with

These are the items from the original sketch that were **deliberately
left out** because their stated purpose is to evade platform content
matching / duplicate detection, which I won't help build. The first
section below is the rationale; the rest is the technical debt / future
work that *is* on the table and would actually improve the tool.

### Why these are out of scope

- **Watermark removal** (TikTok/Snap/Reels watermarks, channel logos,
  third-party overlays) — exists to repost content stripped of the
  originator's mark. Outside the scope of a legitimate repackaging
  tool, and against most platforms' ToS.
- **Perceptual-hash noise injection / micro-rotation / fps / codec
  shuffling to break fingerprints** — the whole point of those
  transforms is to defeat a duplicate-detection system. A creator tool
  has no reason to do this.
- **QR / code obfuscation** — specifically targets platform scan
  patterns. Not a creator concern.
- **Splitting output into sub-threshold segments** — used to dodge
  length-based duplicate checks.
- **TikTok / Reels direct-upload API** — using the official upload
  endpoints while simultaneously stripping identifying marks is the
  misuse case; integrating the upload API on its own is fine, but
  combined with the above it becomes an evasion pipeline.

If the goal is a normal creator repackaging tool (resize, retag,
re-encode, add music, ship to your own channel), everything in
**"What's implemented"** above already covers it.

### Genuine follow-up work (happy to do any of these)

- **Better progress reporting.** Today the bar is driven by moviepy's
  coarse stage percentages plus a few hand-set checkpoints. A real
  solution parses moviepy's `proglog` output or runs ffmpeg with
  `-progress pipe:1` and forwards per-frame percent to the polling
  endpoint.
- **WebSocket / SSE for progress.** Right now the detail page polls
  `/status/` every 1.5 s. Switching to SSE (Django + a `StreamingHttpResponse`)
  would cut a lot of pointless requests and feel snappier.
- **Job queue.** The thread-dispatcher in `tasks.py` is fine for a
  single user. The first time two people hit "Start" simultaneously,
  the second will fight the first for CPU. Celery + Redis (or even
  `django-q2` to keep the dep tree small) is the standard swap.
- **Upload size limit + chunked uploads.** `DATA_UPLOAD_MAX_MEMORY_SIZE`
  is 50 MB and the streaming handler has no built-in cap. Anything over
  ~100 MB starts to feel fragile. Add either a hard form-level check
  or `django-chunked-upload`.
- **Input probing.** `duration_seconds`, `width`, `height` are nullable
  on the model. Populate them with a `ffprobe` call at upload time so
  the detail page can show "3:21, 1920×1080" and the form can warn on
  aspect-ratio mismatches.
- **Real tests.** `projects/tests.py` is the empty Django stub. The
  `test_assets/` directory already has golden clips (padded 9:16,
  simple resize, source 16:9, …) — a proper test suite would assert
  the output dimensions, audio presence, and codec of each transform
  combination.
- **Trim by start time + end time.** `max_duration` is "trim to first
  N seconds". A creator workflow usually wants "trim 00:05–00:35".
- **Multiple audio tracks / crossfade.** Right now it's one background
  track + original. A real creator often wants a 2–3 song playlist
  with crossfades between cuts.
- **Subtitle / caption burn-in.** Many shorts ship with hardcoded
  captions. `moviepy` + a `.srt` parser is the natural shape.
- **Presets.** "TikTok", "Reels", "YouTube Shorts", "Instagram Feed"
  buttons that fill the form in one click — would be ~30 lines on top
  of the form.
- **Direct "send to phone".** For Shorts/Reels the workflow is upload
  to phone → post. A QR code on the detail page linking to the
  rendered output is the lowest-friction version of that.

Happy to take any of those on — just say the word and which one.
