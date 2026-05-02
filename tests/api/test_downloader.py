from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_downloader.services.downloader import download_video


class RedisWithFailingExpire:
    def __init__(self, redis_client) -> None:
        self.redis_client = redis_client

    async def hset(self, *args, **kwargs):
        return await self.redis_client.hset(*args, **kwargs)

    async def expire(self, *args, **kwargs):
        raise RuntimeError("expire failed")

    def pipeline(self, *args, **kwargs):
        return self.redis_client.pipeline(*args, **kwargs)


class RedisWithFailingSecondPipelineExpire:
    def __init__(self, redis_client) -> None:
        self.redis_client = redis_client
        self.pipeline_expire_calls = 0

    async def hset(self, *args, **kwargs):
        return await self.redis_client.hset(*args, **kwargs)

    async def expire(self, *args, **kwargs):
        return await self.redis_client.expire(*args, **kwargs)

    async def ttl(self, *args, **kwargs):
        return await self.redis_client.ttl(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        return await self.redis_client.delete(*args, **kwargs)

    def pipeline(self, *args, **kwargs):
        return PipelineWithFailingSecondExpire(
            self,
            self.redis_client.pipeline(*args, **kwargs),
        )


class PipelineWithFailingSecondExpire:
    def __init__(self, redis_client: RedisWithFailingSecondPipelineExpire, pipeline) -> None:
        self.redis_client = redis_client
        self.pipeline = pipeline

    def __getattr__(self, name: str):
        return getattr(self.pipeline, name)

    def hset(self, *args, **kwargs):
        return self.pipeline.hset(*args, **kwargs)

    def expire(self, *args, **kwargs):
        self.redis_client.pipeline_expire_calls += 1
        if self.redis_client.pipeline_expire_calls == 2:
            raise RuntimeError("pipeline expire failed")
        return self.pipeline.expire(*args, **kwargs)


@pytest.mark.asyncio
async def test_download_video_sets_source_ready(fake_redis, tmp_download_dir: Path) -> None:
    task_id = "task-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source_file = task_dir / "source.mp4"
    source_file.write_text("fake video")

    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = {
        "title": "Example Video",
        "thumbnail": "https://img.youtube.com/vi/example/0.jpg",
        "requested_downloads": [{"filepath": str(source_file)}],
    }

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.return_value = ydl_instance
        ydl_cls.return_value.__exit__.return_value = False
        await download_video(task_id, "https://youtu.be/example", fake_redis, tmp_download_dir)

    data = await fake_redis.hgetall(f"task:{task_id}")
    assert data["status"] == "source_ready"
    assert data["title"] == "Example Video"
    assert data["source_filename"] == "source.mp4"
    assert data["progress"] == "100"
    assert "output_presets" in data


@pytest.mark.asyncio
async def test_download_video_sets_failed_on_error(fake_redis, tmp_download_dir: Path) -> None:
    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = RuntimeError("video unavailable")
        await download_video("task-fail", "https://youtu.be/missing", fake_redis, tmp_download_dir)

    data = await fake_redis.hgetall("task:task-fail")
    assert data["status"] == "failed"
    assert "video unavailable" in data["error"]


@pytest.mark.asyncio
async def test_download_video_rejects_task_id_path_traversal(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    outside_dir = tmp_download_dir.parent / "outside-task"

    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = {
        "title": "Escaped Video",
        "requested_downloads": [{"filepath": str(outside_dir / "source.mp4")}],
    }

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.return_value = ydl_instance
        ydl_cls.return_value.__exit__.return_value = False
        await download_video(
            "../outside-task",
            "https://youtu.be/example",
            fake_redis,
            tmp_download_dir,
        )

    data = await fake_redis.hgetall("task:../outside-task")
    assert data["status"] == "failed"
    assert not outside_dir.exists()


@pytest.mark.asyncio
async def test_download_video_expire_failure_does_not_leave_processing_state(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFailingExpire(fake_redis)

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = RuntimeError("video unavailable")
        await download_video("task-expire", "https://youtu.be/missing", redis_client, tmp_download_dir)

    data = await fake_redis.hgetall("task:task-expire")
    assert data["status"] == "failed"
    assert await fake_redis.ttl("task:task-expire") > 0


@pytest.mark.asyncio
async def test_download_video_failed_state_pipeline_expire_failure_does_not_leave_processing(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFailingSecondPipelineExpire(fake_redis)

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = RuntimeError("video unavailable")
        await download_video(
            "task-pipeline-expire",
            "https://youtu.be/missing",
            redis_client,
            tmp_download_dir,
        )

    data = await fake_redis.hgetall("task:task-pipeline-expire")
    assert data["status"] == "failed"
    assert await fake_redis.ttl("task:task-pipeline-expire") > 0
