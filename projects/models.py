from django.db import models
from django.utils import timezone
import uuid


def upload_to_original(instance, filename):
    return f"uploads/{instance.pk or uuid.uuid4().hex}/{filename}"


def upload_to_output(instance, filename):
    return f"outputs/{instance.pk or uuid.uuid4().hex}/{filename}"


def upload_to_audio(instance, filename):
    return f"audio/{instance.pk or uuid.uuid4().hex}/{filename}"


ASPECT_RATIO_CHOICES = [
    ("source", "Keep source"),
    ("9:16", "9:16 (vertical / Shorts / Reels / TikTok)"),
    ("16:9", "16:9 (landscape / YouTube)"),
    ("1:1", "1:1 (square / Instagram feed)"),
    ("4:5", "4:5 (Instagram portrait)"),
]

CODEC_CHOICES = [
    ("libx264", "H.264 (libx264) — broadly compatible"),
    ("libx265", "H.265 (libx265) — smaller files, slower"),
    ("libvpx-vp9", "VP9 — web optimised"),
]

FPS_CHOICES = [(24, "24"), (25, "25"), (30, "30"), (50, "50"), (60, "60")]

BITRATE_CHOICES = [
    ("1M", "1 Mbps (small)"),
    ("2M", "2 Mbps (standard)"),
    ("4M", "4 Mbps (high quality)"),
    ("8M", "8 Mbps (very high)"),
]

STATUS_CHOICES = [
    ("draft", "Draft"),
    ("queued", "Queued"),
    ("running", "Running"),
    ("done", "Completed"),
    ("failed", "Failed"),
]


class VideoProject(models.Model):
    """A single video repackaging job."""

    title = models.CharField(max_length=200, blank=True)

    # Source
    original = models.FileField(upload_to=upload_to_original)
    original_filename = models.CharField(max_length=255, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)

    # Audio
    song_url = models.URLField(blank=True)
    song_file = models.FileField(upload_to=upload_to_audio, blank=True)
    music_volume = models.FloatField(
        default=0.8, help_text="Background music volume 0.0–1.0"
    )
    original_audio_volume = models.FloatField(
        default=0.2, help_text="Original audio volume 0.0–1.0"
    )

    # Transforms
    aspect_ratio = models.CharField(
        max_length=10, choices=ASPECT_RATIO_CHOICES, default="9:16"
    )
    pad_color = models.CharField(
        max_length=7, default="#000000", help_text="Background padding colour (hex)"
    )
    codec = models.CharField(max_length=20, choices=CODEC_CHOICES, default="libx264")
    fps = models.IntegerField(choices=FPS_CHOICES, default=30)
    bitrate = models.CharField(max_length=10, choices=BITRATE_CHOICES, default="2M")
    max_duration = models.IntegerField(
        default=0, help_text="Trim to N seconds (0 = keep full duration)"
    )
    ken_burns = models.BooleanField(
        default=False, help_text="Slow pan/zoom (good for photo slideshows)"
    )

    # Output
    output = models.FileField(upload_to=upload_to_output, blank=True)
    output_filename = models.CharField(max_length=255, blank=True)
    output_size_bytes = models.BigIntegerField(null=True, blank=True)

    # State
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    progress = models.IntegerField(default=0, help_text="0–100")
    current_stage = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    log = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.original_filename or f"Project #{self.pk}"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("done", "failed")

    def append_log(self, line: str) -> None:
        ts = timezone.now().strftime("%H:%M:%S")
        self.log = (self.log or "") + f"[{ts}] {line}\n"
        self.save(update_fields=["log", "updated_at"])