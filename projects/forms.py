from django import forms

from .models import VideoProject


# Bootstrap 5 widget class hooks — applied via Meta widgets attrs
_TEXT_CLASSES = "form-control"
_SELECT_CLASSES = "form-select"
_CHECK_CLASSES = "form-check-input"
_RANGE_CLASSES = "form-range"
_FILE_CLASSES = "form-control"
_COLOR_CLASSES = "form-control form-control-color"


class ProjectForm(forms.ModelForm):
    class Meta:
        model = VideoProject
        fields = [
            "title",
            "original",
            "song_url",
            "song_file",
            "music_volume",
            "original_audio_volume",
            "aspect_ratio",
            "pad_color",
            "codec",
            "fps",
            "bitrate",
            "max_duration",
            "start_seconds",
            "end_seconds",
            "ken_burns",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": _TEXT_CLASSES,
                "placeholder": "Optional label",
            }),
            "original": forms.ClearableFileInput(attrs={
                "class": _FILE_CLASSES,
                "accept": "video/*",
            }),
            "song_url": forms.URLInput(attrs={
                "class": _TEXT_CLASSES,
                "placeholder": "https://www.youtube.com/watch?v=... or Spotify link",
            }),
            "song_file": forms.ClearableFileInput(attrs={
                "class": _FILE_CLASSES,
                "accept": "audio/*",
            }),
            "aspect_ratio": forms.Select(attrs={"class": _SELECT_CLASSES}),
            "codec": forms.Select(attrs={"class": _SELECT_CLASSES}),
            "fps": forms.Select(attrs={"class": _SELECT_CLASSES}),
            "bitrate": forms.Select(attrs={"class": _SELECT_CLASSES}),
            "pad_color": forms.TextInput(attrs={
                "type": "color",
                "class": _COLOR_CLASSES,
                "title": "Choose padding colour",
            }),
            "music_volume": forms.NumberInput(attrs={
                "type": "range", "min": "0", "max": "1", "step": "0.05",
                "class": _RANGE_CLASSES,
            }),
            "original_audio_volume": forms.NumberInput(attrs={
                "type": "range", "min": "0", "max": "1", "step": "0.05",
                "class": _RANGE_CLASSES,
            }),
            "max_duration": forms.NumberInput(attrs={
                "class": _TEXT_CLASSES,
                "min": "0",
                "placeholder": "0 = keep full duration",
            }),
            "start_seconds": forms.NumberInput(attrs={
                "class": _TEXT_CLASSES,
                "min": "0",
                "step": "0.1",
                "placeholder": "0",
            }),
            "end_seconds": forms.NumberInput(attrs={
                "class": _TEXT_CLASSES,
                "min": "0",
                "step": "0.1",
                "placeholder": "0 = until end",
            }),
            "ken_burns": forms.CheckboxInput(attrs={"class": _CHECK_CLASSES}),
        }

    def clean(self):
        cleaned = super().clean()
        song_url = cleaned.get("song_url")
        song_file = cleaned.get("song_file")
        original = cleaned.get("original")

        # Trim-window validation runs first so the user sees the specific
        # problem even if they forgot to attach a file.
        start = cleaned.get("start_seconds") or 0.0
        end = cleaned.get("end_seconds") or 0.0
        if start < 0 or end < 0:
            raise forms.ValidationError("Start and end seconds must be >= 0.")
        if end and start and end <= start:
            raise forms.ValidationError(
                "End seconds must be greater than start seconds."
            )

        if not original:
            raise forms.ValidationError("Please upload a source video.")
        if not song_url and not song_file:
            # Allowed — keeps original audio only
            pass
        if song_url and song_file:
            raise forms.ValidationError(
                "Provide either a song URL or an uploaded audio file, not both."
            )
        return cleaned