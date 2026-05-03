from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

SourceStatus = Literal["source_pending", "source_processing", "source_ready", "failed"]
ConversionStatus = Literal[
    "conversion_pending",
    "conversion_processing",
    "conversion_ready",
    "failed",
]
VideoFormat = Literal["mp4", "webm", "mkv", "avi", "mov"]
AudioFormat = Literal["mp3", "wav", "flac", "aac", "ogg", "m4a"]
OutputFormat = VideoFormat | AudioFormat
VideoQuality = Literal["1080p", "720p", "480p"]

DEFAULT_VIDEO_PRESETS = [
    {"format": "mp4", "quality": "1080p"},
    {"format": "mp4", "quality": "720p"},
    {"format": "mp4", "quality": "480p"},
    {"format": "webm", "quality": "1080p"},
    {"format": "webm", "quality": "720p"},
    {"format": "mkv", "quality": "1080p"},
    {"format": "avi", "quality": "720p"},
    {"format": "mov", "quality": "1080p"},
]
DEFAULT_AUDIO_PRESETS = [
    {"format": "mp3"},
    {"format": "wav"},
    {"format": "flac"},
    {"format": "aac"},
    {"format": "ogg"},
    {"format": "m4a"},
]

VIDEO_FORMATS = {"mp4", "webm", "mkv", "avi", "mov"}
AUDIO_FORMATS = {"mp3", "wav", "flac", "aac", "ogg", "m4a"}
VIDEO_QUALITIES = {"1080p", "720p", "480p"}
VIDEO_PRESET_PAIRS = {
    (preset["format"], preset["quality"]) for preset in DEFAULT_VIDEO_PRESETS
}
AUDIO_PRESET_FORMATS = {preset["format"] for preset in DEFAULT_AUDIO_PRESETS}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def validate_output_preset(format: OutputFormat, quality: VideoQuality | None) -> None:
    if format in AUDIO_FORMATS and quality is not None:
        raise ValueError("Audio formats do not accept quality")
    if format in AUDIO_FORMATS and format not in AUDIO_PRESET_FORMATS:
        raise ValueError("Unsupported output preset")
    if format in VIDEO_FORMATS and quality is None:
        raise ValueError("Video formats require quality")
    if format in VIDEO_FORMATS and (format, quality) not in VIDEO_PRESET_PAIRS:
        raise ValueError("Unsupported output preset")


class TaskCreateRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        host = (value.host or "").lower()
        if value.scheme == "https" and host in YOUTUBE_HOSTS:
            return value
        raise ValueError("Only YouTube URLs are supported")


class TaskCreateResponse(BaseModel):
    task_id: str
    status: Literal["source_pending"]


class FormatPreset(BaseModel):
    format: OutputFormat
    quality: VideoQuality | None = None

    @model_validator(mode="after")
    def validate_format_quality_pair(self) -> "FormatPreset":
        validate_output_preset(self.format, self.quality)
        return self


class OutputPresets(BaseModel):
    video: list[FormatPreset]
    audio: list[FormatPreset]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: SourceStatus
    title: str | None = None
    thumbnail: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    message: str | None = None
    output_presets: OutputPresets | None = None
    error: str | None = None


class ConversionCreateRequest(BaseModel):
    format: OutputFormat
    quality: VideoQuality | None = None

    @model_validator(mode="after")
    def validate_format_quality_pair(self) -> "ConversionCreateRequest":
        validate_output_preset(self.format, self.quality)
        return self


class ConversionCreateResponse(BaseModel):
    conversion_id: str
    task_id: str
    status: Literal["conversion_pending"]


class ConversionStatusResponse(BaseModel):
    conversion_id: str
    task_id: str
    status: ConversionStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    message: str | None = None
    download_url: str | None = None
    error: str | None = None
