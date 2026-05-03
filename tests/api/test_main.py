import asyncio
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from yt_downloader import main as main_module
from yt_downloader.config import settings


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_cleanup_loop(
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    cleanup_started = asyncio.Event()
    sleep_started = asyncio.Event()
    sleep_cancelled = asyncio.Event()
    cleanup_calls = []

    async def fake_get_redis() -> object:
        return object()

    async def fake_close_redis() -> None:
        return None

    def fake_cleanup_expired_files(*, download_dir: Path, ttl_hours: int) -> None:
        cleanup_calls.append((download_dir, ttl_hours))
        loop.call_soon_threadsafe(cleanup_started.set)

    async def fake_sleep(seconds: float) -> None:
        assert seconds == settings.cleanup_interval_minutes * 60
        sleep_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            sleep_cancelled.set()
            raise

    monkeypatch.setattr(settings, "download_dir", tmp_download_dir)
    monkeypatch.setattr(settings, "file_ttl_hours", 7)
    monkeypatch.setattr(settings, "cleanup_interval_minutes", 3)
    monkeypatch.setattr(main_module, "get_redis", fake_get_redis)
    monkeypatch.setattr(main_module, "close_redis", fake_close_redis)
    monkeypatch.setattr(
        main_module,
        "cleanup_expired_files",
        fake_cleanup_expired_files,
        raising=False,
    )
    monkeypatch.setattr(main_module, "_sleep", fake_sleep, raising=False)

    app = main_module.create_app()
    async with main_module.lifespan(app):
        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        await asyncio.wait_for(sleep_started.wait(), timeout=1)

    assert cleanup_calls == [(tmp_download_dir, 7)]
    assert app.state.cleanup_task.cancelled()
    assert sleep_cancelled.is_set()


@pytest.mark.asyncio
async def test_lifespan_cleanup_loop_continues_after_cleanup_error(
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_retried = asyncio.Event()
    sleep_cancelled = asyncio.Event()
    cleanup_calls = 0

    async def fake_get_redis() -> object:
        return object()

    async def fake_close_redis() -> None:
        return None

    def fake_cleanup_expired_files(*, download_dir: Path, ttl_hours: int) -> None:
        nonlocal cleanup_calls
        assert download_dir == tmp_download_dir
        assert ttl_hours == 7
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise RuntimeError("cleanup failed")

    async def fake_sleep(seconds: float) -> None:
        assert seconds == settings.cleanup_interval_minutes * 60
        if cleanup_calls < 2:
            return
        cleanup_retried.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            sleep_cancelled.set()
            raise

    monkeypatch.setattr(settings, "download_dir", tmp_download_dir)
    monkeypatch.setattr(settings, "file_ttl_hours", 7)
    monkeypatch.setattr(settings, "cleanup_interval_minutes", 3)
    monkeypatch.setattr(main_module, "get_redis", fake_get_redis)
    monkeypatch.setattr(main_module, "close_redis", fake_close_redis)
    monkeypatch.setattr(main_module, "cleanup_expired_files", fake_cleanup_expired_files)
    monkeypatch.setattr(main_module, "_sleep", fake_sleep)

    app = main_module.create_app()
    async with main_module.lifespan(app):
        await asyncio.wait_for(cleanup_retried.wait(), timeout=1)

    assert cleanup_calls == 2
    assert app.state.cleanup_task.cancelled()
    assert sleep_cancelled.is_set()


@pytest.mark.asyncio
async def test_cleanup_loop_logs_cleanup_error(
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cleanup_calls = 0

    def fake_cleanup_expired_files(*, download_dir: Path, ttl_hours: int) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise RuntimeError("cleanup failed")

    async def fake_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(settings, "download_dir", tmp_download_dir)
    monkeypatch.setattr(settings, "file_ttl_hours", 7)
    monkeypatch.setattr(main_module, "cleanup_expired_files", fake_cleanup_expired_files)
    monkeypatch.setattr(main_module, "_sleep", fake_sleep)

    caplog.set_level(logging.ERROR, logger="yt_downloader.main")

    with pytest.raises(asyncio.CancelledError):
        await main_module.cleanup_loop()

    assert cleanup_calls == 1
    assert "Cleanup task failed" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_cancels_pending_download_task_from_route(
    fake_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    spawned_tasks: list[asyncio.Task] = []

    async def fake_cleanup_loop() -> None:
        await asyncio.Future()

    async def fake_download_video(*args, **kwargs) -> None:
        task = asyncio.current_task()
        assert task is not None
        spawned_tasks.append(task)
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main_module, "cleanup_loop", fake_cleanup_loop)
    app = main_module.create_app()
    app.state.redis = fake_redis

    try:
        with patch("yt_downloader.routes.tasks.download_video", fake_download_video):
            async with main_module.lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/tasks",
                        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                    )

                assert response.status_code == 201
                await asyncio.wait_for(started.wait(), timeout=1)

        assert cancelled.is_set()
        assert spawned_tasks and spawned_tasks[0].cancelled()
        assert app.state.background_tasks == set()
    finally:
        for task in spawned_tasks:
            task.cancel()
        await asyncio.gather(*spawned_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_lifespan_cancels_pending_conversion_task_from_route(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    spawned_tasks: list[asyncio.Task] = []
    task_id = "task-1"

    async def fake_cleanup_loop() -> None:
        await asyncio.Future()

    async def fake_convert_file(**kwargs) -> None:
        task = asyncio.current_task()
        assert task is not None
        spawned_tasks.append(task)
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    (task_dir / "source.mp4").write_text("fake video")
    await fake_redis.hset(
        f"task:{task_id}",
        mapping={"status": "source_ready", "source_filename": "source.mp4"},
    )
    monkeypatch.setattr(settings, "download_dir", tmp_download_dir)
    monkeypatch.setattr(main_module, "cleanup_loop", fake_cleanup_loop)
    app = main_module.create_app()
    app.state.redis = fake_redis

    try:
        with patch("yt_downloader.routes.conversions.convert_file", fake_convert_file):
            async with main_module.lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        f"/api/tasks/{task_id}/conversions",
                        json={"format": "mp3", "quality": None},
                    )

                assert response.status_code == 201
                await asyncio.wait_for(started.wait(), timeout=1)

        assert cancelled.is_set()
        assert spawned_tasks and spawned_tasks[0].cancelled()
        assert app.state.background_tasks == set()
    finally:
        for task in spawned_tasks:
            task.cancel()
        await asyncio.gather(*spawned_tasks, return_exceptions=True)
