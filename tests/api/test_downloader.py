import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_downloader.config import settings
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


class PipelineWithFalseExpireResult:
    async def hset(self, *args, **kwargs):
        return 1

    async def expire(self, *args, **kwargs):
        return 0

    async def execute(self):
        return [1, 0]

    async def reset(self):
        return None


class RedisWithFalsePipelineExpireAndFailingFallback:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def pipeline(self, *args, **kwargs):
        return PipelineWithFalseExpireResult()

    async def hset(self, *args, **kwargs):
        return 1

    async def ttl(self, *args, **kwargs):
        return -1

    async def expire(self, *args, **kwargs):
        return 0

    async def delete(self, key: str):
        self.deleted_keys.append(key)
        return 1


class PipelineWithFirstFalseExpireResult:
    def __init__(self, redis_client: "RedisWithInitialFalsePipelineExpire", pipeline) -> None:
        self.redis_client = redis_client
        self.pipeline = pipeline

    def hset(self, *args, **kwargs):
        return self.pipeline.hset(*args, **kwargs)

    def expire(self, *args, **kwargs):
        return self.pipeline.expire(*args, **kwargs)

    async def execute(self):
        results = await self.pipeline.execute()
        self.redis_client.pipeline_execute_calls += 1
        if self.redis_client.pipeline_execute_calls == 1:
            return [results[0], 0]
        return results

    async def reset(self):
        return await self.pipeline.reset()


class RedisWithInitialFalsePipelineExpire:
    def __init__(self, redis_client) -> None:
        self.redis_client = redis_client
        self.pipeline_execute_calls = 0

    async def hset(self, *args, **kwargs):
        return await self.redis_client.hset(*args, **kwargs)

    async def expire(self, *args, **kwargs):
        return await self.redis_client.expire(*args, **kwargs)

    async def ttl(self, *args, **kwargs):
        return await self.redis_client.ttl(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        return await self.redis_client.delete(*args, **kwargs)

    def pipeline(self, *args, **kwargs):
        return PipelineWithFirstFalseExpireResult(
            self,
            self.redis_client.pipeline(*args, **kwargs),
        )


class RedisWithFullyFailingFailureState:
    def pipeline(self, *args, **kwargs):
        raise RuntimeError("pipeline unavailable")

    async def hset(self, *args, **kwargs):
        raise RuntimeError("hset unavailable")

    async def delete(self, *args, **kwargs):
        raise RuntimeError("delete unavailable")


class RedisWithFailingWritesAndNoopDelete:
    def pipeline(self, *args, **kwargs):
        raise RuntimeError("pipeline unavailable")

    async def hset(self, *args, **kwargs):
        raise RuntimeError("hset unavailable")

    async def delete(self, *args, **kwargs):
        return 0


class RedisWithFallbackExpireFailureAndSuccessfulDelete:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def pipeline(self, *args, **kwargs):
        raise RuntimeError("pipeline unavailable")

    async def hset(self, *args, **kwargs):
        return 1

    async def expire(self, *args, **kwargs):
        raise RuntimeError("expire unavailable")

    async def delete(self, key: str):
        self.deleted_keys.append(key)
        return 1


class RedisWithFallbackExpireNoopAndSuccessfulDelete:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def pipeline(self, *args, **kwargs):
        raise RuntimeError("pipeline unavailable")

    async def hset(self, *args, **kwargs):
        return 1

    async def ttl(self, *args, **kwargs):
        return -1

    async def expire(self, *args, **kwargs):
        return 0

    async def delete(self, key: str):
        self.deleted_keys.append(key)
        return 1


@pytest.mark.asyncio
async def test_download_video_sets_source_ready(fake_redis, tmp_download_dir: Path) -> None:
    task_id = "task-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source_file = task_dir / "video title.mp4"
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
    options = ydl_cls.call_args.args[0]
    assert data["status"] == "source_ready"
    assert data["title"] == "Example Video"
    assert data["source_filename"] == f"{task_id}.mp4"
    assert data["progress"] == "100"
    assert "output_presets" in data
    assert options["outtmpl"] == str(task_dir / f"{task_id}.%(ext)s")


@pytest.mark.asyncio
async def test_download_video_reports_source_download_progress(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-progress"
    task_dir = tmp_download_dir / task_id
    source_file = task_dir / "source.webm"
    loop = asyncio.get_running_loop()
    progress_snapshots: list[dict[str, str]] = []

    ydl_instance = MagicMock()

    def extract_info(url: str, download: bool) -> dict:
        options = ydl_cls.call_args.args[0]
        hook = options["progress_hooks"][0]
        hook(
            {
                "status": "downloading",
                "downloaded_bytes": 250,
                "total_bytes": 1000,
            }
        )
        progress_snapshots.append(
            asyncio.run_coroutine_threadsafe(
                fake_redis.hgetall(f"task:{task_id}"),
                loop,
            ).result(timeout=1)
        )
        return {
            "title": "Progress Video",
            "requested_downloads": [{"filepath": str(source_file)}],
        }

    ydl_instance.extract_info.side_effect = extract_info

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.return_value = ydl_instance
        ydl_cls.return_value.__exit__.return_value = False
        await download_video(task_id, "https://youtu.be/progress", fake_redis, tmp_download_dir)

    options = ydl_cls.call_args.args[0]
    data = await fake_redis.hgetall(f"task:{task_id}")
    assert "progress_hooks" in options
    assert len(options["progress_hooks"]) == 1
    assert progress_snapshots == [
        {
            "status": "source_processing",
            "progress": "25",
        }
    ]
    assert data["status"] == "source_ready"
    assert data["source_filename"] == f"{task_id}.webm"
    assert data["progress"] == "100"


@pytest.mark.asyncio
async def test_download_video_ignores_progress_without_usable_total_bytes(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-progress-no-total"
    task_dir = tmp_download_dir / task_id
    source_file = task_dir / "source.mp4"

    ydl_instance = MagicMock()

    def extract_info(url: str, download: bool) -> dict:
        options = ydl_cls.call_args.args[0]
        options["progress_hooks"][0](
            {
                "status": "downloading",
                "downloaded_bytes": 250,
            }
        )
        return {
            "title": "No Total Video",
            "requested_downloads": [{"filepath": str(source_file)}],
        }

    ydl_instance.extract_info.side_effect = extract_info

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.return_value = ydl_instance
        ydl_cls.return_value.__exit__.return_value = False
        await download_video(task_id, "https://youtu.be/no-total", fake_redis, tmp_download_dir)

    data = await fake_redis.hgetall(f"task:{task_id}")
    assert data["status"] == "source_ready"
    assert data["source_filename"] == f"{task_id}.mp4"
    assert data["progress"] == "100"


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


@pytest.mark.asyncio
async def test_download_video_raises_when_failure_state_cannot_persist(
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFullyFailingFailureState()

    with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
        await download_video(
            "task-failure-state",
            "https://youtu.be/missing",
            redis_client,
            tmp_download_dir,
        )


@pytest.mark.asyncio
async def test_download_video_raises_when_failure_state_delete_is_noop(
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFailingWritesAndNoopDelete()

    with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
        await download_video(
            "task-failure-state-noop-delete",
            "https://youtu.be/missing",
            redis_client,
            tmp_download_dir,
        )


@pytest.mark.asyncio
async def test_download_video_raises_when_failure_state_expire_fails_after_fallback_hset(
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFallbackExpireFailureAndSuccessfulDelete()

    with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
        await download_video(
            "task-failure-state-expire",
            "https://youtu.be/missing",
            redis_client,
            tmp_download_dir,
        )

    assert redis_client.deleted_keys == ["task:task-failure-state-expire"]


@pytest.mark.asyncio
async def test_download_video_raises_when_failure_state_expire_returns_zero_after_fallback_hset(
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFallbackExpireNoopAndSuccessfulDelete()

    with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
        await download_video(
            "task-failure-state-expire-zero",
            "https://youtu.be/missing",
            redis_client,
            tmp_download_dir,
        )

    assert redis_client.deleted_keys == ["task:task-failure-state-expire-zero"]


@pytest.mark.asyncio
async def test_download_video_raises_when_pipeline_failure_state_expire_returns_false(
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFalsePipelineExpireAndFailingFallback()

    with patch("yt_downloader.services.downloader.yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = RuntimeError("video unavailable")
        with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
            await download_video(
                "task-pipeline-expire-false",
                "https://youtu.be/missing",
                redis_client,
                tmp_download_dir,
            )

    assert redis_client.deleted_keys == [
        "task:task-pipeline-expire-false",
        "task:task-pipeline-expire-false",
        "task:task-pipeline-expire-false",
    ]


@pytest.mark.asyncio
async def test_download_video_raises_when_primary_state_pipeline_expire_returns_false(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-primary-expire-false"
    redis_client = RedisWithInitialFalsePipelineExpire(fake_redis)

    with pytest.raises(RuntimeError, match="Failed to persist task state"):
        await download_video(
            task_id,
            "https://youtu.be/example",
            redis_client,
            tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"task:{task_id}")
    assert data["status"] == "failed"
    assert "failed to set state TTL" in data["error"]
    assert await fake_redis.ttl(f"task:{task_id}") > 0


@pytest.mark.asyncio
async def test_download_video_raises_when_runtime_file_ttl_is_zero(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "file_ttl_hours", 0)

    with pytest.raises(RuntimeError, match="Failed to persist task failure state"):
        await download_video(
            "task-zero-ttl",
            "https://youtu.be/missing",
            fake_redis,
            tmp_download_dir,
        )

    assert await fake_redis.hgetall("task:task-zero-ttl") == {}
