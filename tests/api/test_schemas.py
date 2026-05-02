import json

import pytest
from pydantic import BaseModel
from pydantic import ValidationError

from yt_downloader.config import Settings
from yt_downloader.models.schemas import (
    ConversionCreateRequest,
    ConversionCreateResponse,
    ConversionStatusResponse,
    FormatPreset,
    OutputPresets,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskStatusResponse,
)


class TestTaskCreateRequest:
    def test_accepts_youtube_url(self) -> None:
        req = TaskCreateRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert str(req.url).startswith("https://www.youtube.com/watch")

    def test_accepts_short_youtube_url(self) -> None:
        req = TaskCreateRequest(url="https://youtu.be/dQw4w9WgXcQ")
        assert req.url.host == "youtu.be"

    def test_rejects_arbitrary_youtube_subdomain(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest(url="https://foo.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_plain_http_youtube_url(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest(url="http://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_non_youtube_url(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest(url="https://example.com/watch?v=dQw4w9WgXcQ")


class TestSettings:
    def test_ignores_unrelated_dotenv_keys(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "GATEWAY_PORT=17291",
                    "REDIS_URL=redis://localhost:6379/1",
                    "FILE_TTL_HOURS=12",
                ]
            ),
            encoding="utf-8",
        )

        settings = Settings(_env_file=env_file)

        assert settings.redis_url == "redis://localhost:6379/1"
        assert settings.file_ttl_hours == 12

    def test_video_presets_are_json_serializable_dicts(self) -> None:
        settings = Settings(_env_file=None)

        json.dumps(settings.video_presets)
        assert settings.video_presets[0] == {"format": "mp4", "quality": "1080p"}
        assert not isinstance(settings.video_presets[0], BaseModel)

    def test_rejects_invalid_configured_video_presets(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, video_presets=[{"format": "mkv", "quality": "480p"}])

    def test_audio_presets_are_normalized_without_quality(self) -> None:
        settings = Settings(_env_file=None, audio_presets=[{"format": "mp3", "quality": None}])

        assert settings.audio_presets == [{"format": "mp3"}]


class TestFormatPreset:
    def test_rejects_audio_preset_with_quality(self) -> None:
        with pytest.raises(ValidationError):
            FormatPreset(format="mp3", quality="720p")

    def test_rejects_non_whitelisted_video_preset(self) -> None:
        with pytest.raises(ValidationError):
            FormatPreset(format="mkv", quality="480p")

    def test_rejects_video_preset_without_quality(self) -> None:
        with pytest.raises(ValidationError):
            FormatPreset(format="mp4")


class TestTaskResponses:
    def test_create_response_status(self) -> None:
        resp = TaskCreateResponse(task_id="task-1", status="source_pending")
        assert resp.status == "source_pending"

    def test_processing_response_allows_nullable_metadata(self) -> None:
        resp = TaskStatusResponse(
            task_id="task-1",
            status="source_processing",
            title=None,
            thumbnail=None,
            progress=42,
            message="下載中",
        )
        assert resp.progress == 42

    def test_source_ready_response_with_presets(self) -> None:
        resp = TaskStatusResponse(
            task_id="task-1",
            status="source_ready",
            title="Example",
            thumbnail="https://img.youtube.com/vi/example/0.jpg",
            progress=100,
            output_presets=OutputPresets(
                video=[FormatPreset(format="mp4", quality="1080p")],
                audio=[FormatPreset(format="mp3")],
            ),
        )
        assert resp.output_presets.video[0].format == "mp4"
        assert resp.output_presets.audio[0].quality is None

    def test_failed_response(self) -> None:
        resp = TaskStatusResponse(task_id="task-1", status="failed", error="boom")
        assert resp.error == "boom"


class TestConversionCreateRequest:
    def test_audio_conversion_request(self) -> None:
        req = ConversionCreateRequest(format="mp3", quality=None)
        assert req.format == "mp3"

    def test_video_conversion_request(self) -> None:
        req = ConversionCreateRequest(format="mp4", quality="720p")
        assert req.quality == "720p"

    def test_rejects_quality_for_audio(self) -> None:
        with pytest.raises(ValidationError):
            ConversionCreateRequest(format="mp3", quality="720p")

    def test_rejects_unknown_format(self) -> None:
        with pytest.raises(ValidationError):
            ConversionCreateRequest(format="exe", quality=None)

    def test_rejects_non_whitelisted_video_preset(self) -> None:
        with pytest.raises(ValidationError):
            ConversionCreateRequest(format="mkv", quality="480p")


class TestConversionResponses:
    def test_create_response(self) -> None:
        resp = ConversionCreateResponse(
            conversion_id="conv-1",
            task_id="task-1",
            status="conversion_pending",
        )
        assert resp.conversion_id == "conv-1"

    def test_ready_response(self) -> None:
        resp = ConversionStatusResponse(
            conversion_id="conv-1",
            task_id="task-1",
            status="conversion_ready",
            progress=100,
            download_url="/api/conversions/conv-1/download",
        )
        assert resp.download_url == "/api/conversions/conv-1/download"
