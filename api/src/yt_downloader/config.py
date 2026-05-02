from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from yt_downloader.models.schemas import DEFAULT_AUDIO_PRESETS, DEFAULT_VIDEO_PRESETS, FormatPreset


def _normalize_presets(presets: list[Any]) -> list[dict[str, str]]:
    return [
        FormatPreset.model_validate(preset).model_dump(exclude_none=True)
        for preset in presets
    ]


def _video_presets() -> list[dict[str, str]]:
    return _normalize_presets(DEFAULT_VIDEO_PRESETS)


def _audio_presets() -> list[dict[str, str]]:
    return _normalize_presets(DEFAULT_AUDIO_PRESETS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    download_dir: Path = Path("/app/downloads")
    file_ttl_hours: int = 24
    cleanup_interval_minutes: int = 60
    max_concurrent_conversions: int = 1
    video_presets: list[dict[str, str]] = Field(default_factory=_video_presets)
    audio_presets: list[dict[str, str]] = Field(default_factory=_audio_presets)

    @field_validator("video_presets", "audio_presets", mode="before")
    @classmethod
    def validate_presets(cls, value: list[Any]) -> list[dict[str, str]]:
        return _normalize_presets(value)


settings = Settings()
