from pathlib import Path
from unittest.mock import patch

import pytest

from yt_downloader.config import settings
from yt_downloader.services.converter import build_ffmpeg_args, convert_file


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


def test_build_ffmpeg_args_for_mp3(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "source.mp3"
    args = build_ffmpeg_args(source, output, "mp3", None)
    assert "-vn" in args
    assert "libmp3lame" in args
    assert str(output) == args[-1]


def test_build_ffmpeg_args_for_mp4_720p(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "source.mp4"
    args = build_ffmpeg_args(source, output, "mp4", "720p")
    assert "scale=-2:720" in args
    assert "libx264" in args


@pytest.mark.asyncio
async def test_convert_file_sets_conversion_ready(fake_redis, tmp_download_dir: Path) -> None:
    task_id = "task-1"
    conversion_id = "conv-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    expected_output = task_dir / "outputs" / conversion_id / "source.mp3"

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.return_value = expected_output
        expected_output.parent.mkdir(parents=True)
        expected_output.write_text("fake audio")
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=fake_redis,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"conversion:{conversion_id}")
    assert data["status"] == "conversion_ready"
    assert data["output_filename"] == "source.mp3"
    assert data["download_url"] == f"/api/conversions/{conversion_id}/download"


@pytest.mark.asyncio
async def test_convert_file_sets_failed_on_error(fake_redis, tmp_download_dir: Path) -> None:
    task_id = "task-1"
    conversion_id = "conv-fail"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.side_effect = RuntimeError("ffmpeg failed")
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=fake_redis,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"conversion:{conversion_id}")
    assert data["status"] == "failed"
    assert "ffmpeg failed" in data["error"]


@pytest.mark.asyncio
async def test_convert_file_rejects_output_path_traversal(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    safe_task_dir = tmp_download_dir / "task-1"
    safe_task_dir.mkdir()
    source = safe_task_dir / "source.mp4"
    source.write_text("fake video")
    outside_task_dir = tmp_download_dir.parent / "outside-task"
    outside_conv_dir = tmp_download_dir.parent / "outside-conv"

    def write_escaped_output(
        source_path: Path,
        output_path: Path,
        target_format: str,
        quality: str | None,
    ) -> Path:
        output_path.parent.mkdir(parents=True)
        output_path.write_text("escaped")
        return output_path

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.side_effect = write_escaped_output
        await convert_file(
            conversion_id="../outside-conv",
            task_id="../outside-task",
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=fake_redis,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall("conversion:../outside-conv")
    assert data["status"] == "failed"
    assert not outside_task_dir.exists()
    assert not outside_conv_dir.exists()


@pytest.mark.asyncio
async def test_convert_file_expire_failure_does_not_leave_processing_state(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFailingExpire(fake_redis)
    task_id = "task-1"
    conversion_id = "conv-expire"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.side_effect = RuntimeError("ffmpeg failed")
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"conversion:{conversion_id}")
    assert data["status"] == "failed"
    assert await fake_redis.ttl(f"conversion:{conversion_id}") > 0


@pytest.mark.asyncio
async def test_convert_file_raises_when_failure_state_cannot_persist(
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-failure-state"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithFullyFailingFailureState()

    with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )


@pytest.mark.asyncio
async def test_convert_file_raises_when_failure_state_delete_is_noop(
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-failure-state-noop-delete"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithFailingWritesAndNoopDelete()

    with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )


@pytest.mark.asyncio
async def test_convert_file_raises_when_failure_state_expire_fails_after_fallback_hset(
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-failure-state-expire"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithFallbackExpireFailureAndSuccessfulDelete()

    with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    assert redis_client.deleted_keys == [f"conversion:{conversion_id}"]


@pytest.mark.asyncio
async def test_convert_file_raises_when_failure_state_expire_returns_zero_after_fallback_hset(
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-failure-state-expire-zero"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithFallbackExpireNoopAndSuccessfulDelete()

    with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    assert redis_client.deleted_keys == [f"conversion:{conversion_id}"]


@pytest.mark.asyncio
async def test_convert_file_raises_when_pipeline_failure_state_expire_returns_false(
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-pipeline-expire-false"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithFalsePipelineExpireAndFailingFallback()

    with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    assert redis_client.deleted_keys == [
        f"conversion:{conversion_id}",
        f"conversion:{conversion_id}",
        f"conversion:{conversion_id}",
    ]


@pytest.mark.asyncio
async def test_convert_file_raises_when_primary_state_pipeline_expire_returns_false(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-primary-expire-false"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    redis_client = RedisWithInitialFalsePipelineExpire(fake_redis)

    with pytest.raises(RuntimeError, match="Failed to persist conversion state"):
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"conversion:{conversion_id}")
    assert data["status"] == "failed"
    assert data["task_id"] == task_id
    assert "failed to set state TTL" in data["error"]
    assert await fake_redis.ttl(f"conversion:{conversion_id}") > 0


@pytest.mark.asyncio
async def test_convert_file_raises_when_runtime_file_ttl_is_zero(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-zero-ttl"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    monkeypatch.setattr(settings, "file_ttl_hours", 0)

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.side_effect = RuntimeError("ffmpeg failed")
        with pytest.raises(RuntimeError, match="Failed to persist conversion failure state"):
            await convert_file(
                conversion_id=conversion_id,
                task_id=task_id,
                source_path=source,
                target_format="mp3",
                quality=None,
                redis_client=fake_redis,
                download_dir=tmp_download_dir,
            )

    assert await fake_redis.hgetall(f"conversion:{conversion_id}") == {}


@pytest.mark.asyncio
async def test_convert_file_failed_state_pipeline_expire_failure_does_not_leave_processing(
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    redis_client = RedisWithFailingSecondPipelineExpire(fake_redis)
    task_id = "task-1"
    conversion_id = "conv-pipeline-expire"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")

    with patch("yt_downloader.services.converter._run_ffmpeg") as run_ffmpeg:
        run_ffmpeg.side_effect = RuntimeError("ffmpeg failed")
        await convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source,
            target_format="mp3",
            quality=None,
            redis_client=redis_client,
            download_dir=tmp_download_dir,
        )

    data = await fake_redis.hgetall(f"conversion:{conversion_id}")
    assert data["status"] == "failed"
    assert await fake_redis.ttl(f"conversion:{conversion_id}") > 0
