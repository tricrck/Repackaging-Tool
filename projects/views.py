import json
import mimetypes
import os
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import ProjectForm
from .models import STATUS_CHOICES, VideoProject
from .tasks import start_in_thread


def index(request):
    recent = VideoProject.objects.all()[:6]
    return render(request, "projects/index.html", {"recent": recent})


def project_list(request):
    qs = VideoProject.objects.all()
    status_filter = request.GET.get("status")
    if status_filter and status_filter in dict(STATUS_CHOICES):
        qs = qs.filter(status=status_filter)
    return render(request, "projects/list.html", {
        "projects": qs,
        "status_filter": status_filter,
        "status_choices": STATUS_CHOICES,
    })


@require_http_methods(["GET", "POST"])
def project_new(request):
    if request.method == "POST":
        form = ProjectForm(request.POST, request.FILES)
        if form.is_valid():
            project = form.save(commit=False)
            upload = form.cleaned_data["original"]
            project.original_filename = upload.name
            project.status = "queued"
            project.save()
            # Probe the freshly-saved upload so the detail page can show
            # duration / dimensions without re-running ffprobe later.
            _populate_metadata(project)
            messages.success(request, f"Project #{project.pk} created — kicking off pipeline.")
            start_in_thread(project.pk)
            return redirect("project_detail", pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, "projects/new.html", {"form": form})


def _populate_metadata(project: "VideoProject") -> None:
    """Probe the source video and write duration/width/height onto the row."""
    from .services.probe import probe, ffprobe_available
    if not ffprobe_available():
        return
    try:
        info = probe(project.original.path)
    except Exception:  # noqa: BLE001
        return
    if not info:
        return
    project.duration_seconds = info["duration"] or None
    project.width = info["width"] or None
    project.height = info["height"] or None
    project.save(update_fields=["duration_seconds", "width", "height", "updated_at"])


def project_detail(request, pk: int):
    project = get_object_or_404(VideoProject, pk=pk)
    return render(request, "projects/detail.html", {"project": project})


@require_POST
def project_start(request, pk: int):
    project = get_object_or_404(VideoProject, pk=pk)
    if project.status in ("running", "queued"):
        messages.warning(request, "Project is already running.")
        return redirect("project_detail", pk=pk)
    project.status = "queued"
    project.progress = 0
    project.error_message = ""
    project.save(update_fields=["status", "progress", "error_message", "updated_at"])
    start_in_thread(project.pk)
    messages.success(request, "Pipeline restarted.")
    return redirect("project_detail", pk=pk)


@require_GET
def project_status(request, pk: int):
    """JSON endpoint polled by the detail page for live progress."""
    project = get_object_or_404(VideoProject, pk=pk)
    return JsonResponse({
        "pk": project.pk,
        "status": project.status,
        "progress": project.progress,
        "current_stage": project.current_stage,
        "error_message": project.error_message,
        "log": project.log,
        "has_output": bool(project.output),
        "download_url": reverse("project_download", args=[project.pk]) if project.output else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    })


def project_download(request, pk: int):
    project = get_object_or_404(VideoProject, pk=pk)
    if not project.output:
        raise Http404("No output yet")
    path = Path(project.output.path)
    if not path.exists():
        raise Http404("Output file missing on disk")
    download_name = project.output_filename or path.name
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=download_name,
        content_type="video/mp4",
    )


@require_POST
def project_delete(request, pk: int):
    project = get_object_or_404(VideoProject, pk=pk)
    # Clean up media files (best-effort)
    for f in [project.original, project.song_file, project.output]:
        if f:
            try:
                path = Path(f.path)
                if path.exists():
                    path.unlink()
            except Exception:
                pass
    project.delete()
    messages.success(request, "Project deleted.")
    return redirect("project_list")