"""Template tags and filters for the projects app."""
from django import template

from ..services.probe import format_duration

register = template.Library()


@register.filter(name="durationformat")
def durationformat(value):
    """Format a duration in seconds as M:SS (or H:MM:SS)."""
    try:
        seconds = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return "—"
    return format_duration(seconds)
