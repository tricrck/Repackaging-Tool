from django.contrib import admin

from .models import VideoProject


@admin.register(VideoProject)
class VideoProjectAdmin(admin.ModelAdmin):
    list_display = ("pk", "title", "status", "progress", "created_at", "completed_at")
    list_filter = ("status", "codec", "aspect_ratio")
    readonly_fields = (
        "status", "progress", "current_stage", "error_message", "log",
        "duration_seconds", "width", "height",
        "output", "output_filename", "output_size_bytes",
        "started_at", "completed_at", "created_at", "updated_at",
    )