import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from yt_downloader.config import settings
from yt_downloader.services import converter
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


class CompletedProcess:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def __iter__(self):
        return iter(self.lines)


class FakePopen:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        command = args[0]
        assert "-progress" in command
        assert command[command.index("-progress") + 1] == "pipe:1"
        assert "-nostats" in command
        self.stdout = FakeStdout(
            [
                "out_time_ms=2500000\n",
                "progress=continue\n",
                "out_time=00:00:05.000000\n",
                "progress=continue\n",
                "out_time_us=12500000\n",
                "progress=end\n",
            ]
        )
        self.stderr = None
        self.returncode = 0

    def communicate(self):
        return "", ""

    def poll(self):
        return self.returncode

    def wait(self, timeout: float | None = None):
        return self.returncode


class BlockingStdout:
    def __init__(self, stderr_drained: threading.Event) -> None:
        self.stderr_drained = stderr_drained

    def __iter__(self):
        yield "out_time_ms=2500000\n"
        if not self.stderr_drained.wait(timeout=0.2):
            raise AssertionError("ffmpeg stderr was not drained while stdout was active")
        yield "progress=end\n"


class ObservableStderr:
    def __init__(self, stderr_drained: threading.Event) -> None:
        self.stderr_drained = stderr_drained

    def __iter__(self):
        self.stderr_drained.set()
        return iter(["ffmpeg warning\n"])


class FakePopenWithBusyStderr:
    instance: "FakePopenWithBusyStderr | None" = None

    def __init__(self, *args, **kwargs) -> None:
        stderr_drained = threading.Event()
        self.stdout = BlockingStdout(stderr_drained)
        self.stderr = ObservableStderr(stderr_drained)
        self.returncode = 0
        self.terminated = False
        self.wait_called = False
        FakePopenWithBusyStderr.instance = self

    def poll(self):
        return self.returncode

    def wait(self, timeout: float | None = None):
        self.wait_called = True
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class FakePopenForCallbackFailure:
    instance: "FakePopenForCallbackFailure | None" = None

    def __init__(self, *args, **kwargs) -> None:
        self.stdout = FakeStdout(["out_time_ms=5000000\n", "progress=end\n"])
        self.stderr = FakeStdout([])
        self.returncode: int | None = None
        self.terminated = False
        self.wait_called = False
        FakePopenForCallbackFailure.instance = self

    def poll(self):
        return self.returncode

    def wait(self, timeout: float | None = None):
        self.wait_called = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class RaisingStream:
    def __iter__(self):
        raise RuntimeError("stream failed")


class AlreadyFinishedProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return 0

    def terminate(self) -> None:
        self.terminated = True


class HangingProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None):
        self.wait_calls += 1
        if timeout is not None:
            raise converter.subprocess.TimeoutExpired("ffmpeg", timeout)
        return -9

    def kill(self) -> None:
        self.killed = True


class FakePopenForMalformedProgressAndFailure:
    def __init__(self, *args, **kwargs) -> None:
        self.stdout = FakeStdout(["not-a-progress-field\n"])
        self.stderr = FakeStdout(["ffmpeg failed\n"])
        self.returncode = 1

    def poll(self):
        return self.returncode

    def wait(self, timeout: float | None = None):
        return self.returncode


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


def test_parse_ffprobe_duration_accepts_positive_float() -> None:
    assert converter._parse_ffprobe_duration("12.345\n") == 12.345


@pytest.mark.parametrize("stdout", ["", "N/A\n", "-1\n", "0\n", "nan\n", "inf\n"])
def test_parse_ffprobe_duration_rejects_unusable_values(stdout: str) -> None:
    assert converter._parse_ffprobe_duration(stdout) is None


def test_probe_duration_falls_back_when_ffprobe_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(converter.subprocess, "run", fake_run)

    assert converter._probe_duration(tmp_path / "source.mp4") is None


@pytest.mark.parametrize("value", ["bad", "aa:00:00"])
def test_parse_ffmpeg_time_rejects_invalid_values(value: str) -> None:
    assert converter._parse_ffmpeg_time(value) is None


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"out_time_ms": "5000000"}, 50),
        ({"out_time_us": "2500000"}, 25),
        ({"out_time": "00:00:07.500000"}, 75),
        ({"out_time": "00:00:12.000000"}, 99),
        ({"out_time_ms": "-1"}, 0),
    ],
)
def test_calculate_ffmpeg_progress_from_supported_fields(
    fields: dict[str, str],
    expected: int,
) -> None:
    assert converter._progress_percent_from_ffmpeg_fields(fields, 10.0) == expected


def test_calculate_ffmpeg_progress_returns_none_without_duration() -> None:
    assert converter._progress_percent_from_ffmpeg_fields({"out_time_ms": "1"}, None) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"out_time_ms": "not-a-number"},
        {"progress": "continue"},
    ],
)
def test_calculate_ffmpeg_progress_returns_none_without_elapsed_time(
    fields: dict[str, str],
) -> None:
    assert converter._progress_percent_from_ffmpeg_fields(fields, 10.0) is None


def test_drain_process_stream_records_stream_errors() -> None:
    lines: list[str] = []

    converter._drain_process_stream(RaisingStream(), lines)

    assert lines == ["stream failed"]


def test_terminate_process_ignores_already_finished_process() -> None:
    process = AlreadyFinishedProcess()

    converter._terminate_process(process)

    assert not process.terminated


def test_terminate_process_kills_after_timeout() -> None:
    process = HangingProcess()

    converter._terminate_process(process)

    assert process.terminated
    assert process.killed
    assert process.wait_calls == 2


def test_run_ffmpeg_raises_stderr_message_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("fake video")
    output = tmp_path / "source.mp3"

    monkeypatch.setattr(converter, "_probe_duration", lambda source_path: 10.0)
    monkeypatch.setattr(converter.subprocess, "Popen", FakePopenForMalformedProgressAndFailure)

    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        converter._run_ffmpeg(source, output, "mp3", None)


def test_run_ffmpeg_drains_stderr_while_reading_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("fake video")
    output = tmp_path / "source.mp3"

    monkeypatch.setattr(converter, "_probe_duration", lambda source_path: 10.0)
    monkeypatch.setattr(converter.subprocess, "Popen", FakePopenWithBusyStderr)

    assert converter._run_ffmpeg(source, output, "mp3", None) == output

    assert FakePopenWithBusyStderr.instance is not None
    assert FakePopenWithBusyStderr.instance.wait_called


def test_run_ffmpeg_stops_process_when_progress_callback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("fake video")
    output = tmp_path / "source.mp3"

    def failing_callback(progress: int) -> None:
        raise RuntimeError("redis failed")

    monkeypatch.setattr(converter, "_probe_duration", lambda source_path: 10.0)
    monkeypatch.setattr(converter.subprocess, "Popen", FakePopenForCallbackFailure)

    with pytest.raises(RuntimeError, match="redis failed"):
        converter._run_ffmpeg(source, output, "mp3", None, failing_callback)

    assert FakePopenForCallbackFailure.instance is not None
    assert FakePopenForCallbackFailure.instance.terminated
    assert FakePopenForCallbackFailure.instance.wait_called


@pytest.mark.asyncio
async def test_convert_file_sets_conversion_ready(fake_redis, tmp_download_dir: Path) -> None:
    task_id = "task-1"
    conversion_id = "conv-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    expected_output = task_dir / "outputs" / conversion_id / f"{task_id}.mp3"

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
    assert data["output_filename"] == f"{task_id}.mp3"
    assert data["download_url"] == f"/api/conversions/{conversion_id}/download"
    assert run_ffmpeg.call_args.args[:4] == (source, expected_output, "mp3", None)
    assert callable(run_ffmpeg.call_args.args[4])


@pytest.mark.asyncio
async def test_convert_file_reports_ffmpeg_progress(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "task-progress"
    conversion_id = "conv-progress"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    snapshots: list[dict[str, str]] = []

    original_write_hash_state = converter.write_hash_state

    async def record_write_hash_state(redis_client, key, mapping, ttl_seconds):
        await original_write_hash_state(redis_client, key, mapping, ttl_seconds)
        if key == f"conversion:{conversion_id}":
            snapshots.append(await fake_redis.hgetall(key))

    def fake_run(args, **kwargs):
        assert args[0] == "ffprobe"
        assert str(source) in args
        return CompletedProcess(returncode=0, stdout="10.0\n")

    monkeypatch.setattr(converter, "write_hash_state", record_write_hash_state)
    monkeypatch.setattr(converter.subprocess, "run", fake_run)
    monkeypatch.setattr(converter.subprocess, "Popen", FakePopen)

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
    output = task_dir / "outputs" / conversion_id / f"{task_id}.mp3"
    progress_values = [snapshot.get("progress") for snapshot in snapshots]

    assert data["status"] == "conversion_ready"
    assert data["progress"] == "100"
    assert output.parent.exists()
    assert progress_values == ["0", "25", "50", "99", "100"]


@pytest.mark.asyncio
async def test_convert_file_succeeds_without_usable_duration(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "task-no-duration"
    conversion_id = "conv-no-duration"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    source = task_dir / "source.mp4"
    source.write_text("fake video")
    snapshots: list[dict[str, str]] = []

    original_write_hash_state = converter.write_hash_state

    async def record_write_hash_state(redis_client, key, mapping, ttl_seconds):
        await original_write_hash_state(redis_client, key, mapping, ttl_seconds)
        if key == f"conversion:{conversion_id}":
            snapshots.append(await fake_redis.hgetall(key))

    def fake_run(args, **kwargs):
        assert args[0] == "ffprobe"
        return CompletedProcess(returncode=1, stderr="ffprobe failed")

    monkeypatch.setattr(converter, "write_hash_state", record_write_hash_state)
    monkeypatch.setattr(converter.subprocess, "run", fake_run)
    monkeypatch.setattr(converter.subprocess, "Popen", FakePopen)

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
    progress_values = [snapshot.get("progress") for snapshot in snapshots]

    assert data["status"] == "conversion_ready"
    assert data["progress"] == "100"
    assert progress_values == ["0", "100"]


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
