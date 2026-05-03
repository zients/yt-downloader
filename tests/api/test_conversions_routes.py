from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI

from yt_downloader.config import settings
from yt_downloader.main import create_app


@pytest_asyncio.fixture
async def app(
    fake_redis,
    tmp_download_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    monkeypatch.setattr(settings, "download_dir", tmp_download_dir)
    application = create_app()
    application.state.redis = fake_redis
    return application


@pytest.mark.asyncio
async def test_create_conversion_returns_pending(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    (task_dir / "source.mp4").write_text("fake video")
    await fake_redis.hset(
        f"task:{task_id}",
        mapping={"status": "source_ready", "source_filename": "source.mp4"},
    )

    with patch("yt_downloader.routes.conversions.convert_file", new_callable=AsyncMock):
        response = await async_client.post(
            f"/api/tasks/{task_id}/conversions",
            json={"format": "mp3", "quality": None},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["conversion_id"]
    assert body["status"] == "conversion_pending"


@pytest.mark.asyncio
async def test_create_conversion_rejects_invalid_route_task_id(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    source_file = tmp_download_dir / "source.mp4"
    source_file.write_text("fake video")
    await fake_redis.hset(
        "task:.",
        mapping={"status": "source_ready", "source_filename": "source.mp4"},
    )

    with patch(
        "yt_downloader.routes.conversions.convert_file",
        new_callable=AsyncMock,
    ) as convert_file:
        response = await async_client.post(
            "/api/tasks/%2E/conversions",
            json={"format": "mp3", "quality": None},
        )

    assert response.status_code == 400
    convert_file.assert_not_called()


@pytest.mark.asyncio
async def test_create_conversion_rejects_traversal_source_filename(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    victim_dir = tmp_download_dir / "victim"
    victim_dir.mkdir()
    (victim_dir / "source.mp4").write_text("victim video")
    await fake_redis.hset(
        f"task:{task_id}",
        mapping={
            "status": "source_ready",
            "source_filename": "../victim/source.mp4",
        },
    )

    with patch(
        "yt_downloader.routes.conversions.convert_file",
        new_callable=AsyncMock,
    ) as convert_file:
        response = await async_client.post(
            f"/api/tasks/{task_id}/conversions",
            json={"format": "mp3", "quality": None},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"
    convert_file.assert_not_called()


@pytest.mark.asyncio
async def test_create_conversion_nul_source_filename_is_invalid_task_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "task:task-1",
        mapping={"status": "source_ready", "source_filename": "\x00"},
    )

    with patch(
        "yt_downloader.routes.conversions.convert_file",
        new_callable=AsyncMock,
    ) as convert_file:
        response = await async_client.post(
            "/api/tasks/task-1/conversions",
            json={"format": "mp3", "quality": None},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"
    convert_file.assert_not_called()


@pytest.mark.asyncio
async def test_create_conversion_missing_source_filename_is_invalid_task_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "task:task-1",
        mapping={"status": "source_ready"},
    )

    with patch(
        "yt_downloader.routes.conversions.convert_file",
        new_callable=AsyncMock,
    ) as convert_file:
        response = await async_client.post(
            "/api/tasks/task-1/conversions",
            json={"format": "mp3", "quality": None},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"
    convert_file.assert_not_called()


@pytest.mark.asyncio
async def test_create_conversion_requires_source_ready(async_client, fake_redis) -> None:
    await fake_redis.hset("task:task-1", mapping={"status": "source_processing"})

    response = await async_client.post(
        "/api/tasks/task-1/conversions",
        json={"format": "mp3", "quality": None},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_conversion_rejects_invalid_task_status_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset("task:task-1", mapping={"status": "garbage"})

    response = await async_client.post(
        "/api/tasks/task-1/conversions",
        json={"format": "mp3", "quality": None},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"


@pytest.mark.asyncio
async def test_create_conversion_rejects_non_whitelisted_preset(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    (task_dir / "source.mp4").write_text("fake video")
    await fake_redis.hset(
        f"task:{task_id}",
        mapping={"status": "source_ready", "source_filename": "source.mp4"},
    )

    response = await async_client.post(
        f"/api/tasks/{task_id}/conversions",
        json={"format": "mkv", "quality": "480p"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_conversion_ready(async_client, fake_redis) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_ready",
            "task_id": "task-1",
            "progress": "100",
            "download_url": "/api/conversions/conv-1/download",
            "output_filename": "source.mp3",
        },
    )

    response = await async_client.get("/api/conversions/conv-1")

    assert response.status_code == 200
    assert response.json()["status"] == "conversion_ready"


@pytest.mark.asyncio
async def test_get_conversion_rejects_invalid_route_id(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:..",
        mapping={
            "status": "conversion_ready",
            "task_id": "task-1",
            "progress": "100",
        },
    )

    response = await async_client.get("/api/conversions/%2E%2E")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_conversion_rejects_nul_route_id(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:\x00",
        mapping={
            "status": "conversion_ready",
            "task_id": "task-1",
            "progress": "100",
        },
    )

    response = await async_client.get("/api/conversions/%00")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_conversion_missing_task_id_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={"status": "conversion_ready", "progress": "100"},
    )

    response = await async_client.get("/api/conversions/conv-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_get_conversion_invalid_task_id_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_ready",
            "task_id": "../task",
            "progress": "100",
            "download_url": "/api/conversions/conv-1/download",
        },
    )

    response = await async_client.get("/api/conversions/conv-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_get_conversion_nul_task_id_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_ready",
            "task_id": "\x00",
            "progress": "100",
            "download_url": "/api/conversions/conv-1/download",
        },
    )

    response = await async_client.get("/api/conversions/conv-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_get_conversion_invalid_progress_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_processing",
            "task_id": "task-1",
            "progress": "nan",
        },
    )

    response = await async_client.get("/api/conversions/conv-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_get_conversion_not_found(async_client) -> None:
    response = await async_client.get("/api/conversions/missing")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_ready_conversion(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-1"
    output_dir = tmp_download_dir / task_id / "outputs" / conversion_id
    output_dir.mkdir(parents=True)
    output_file = output_dir / f"{task_id}.mp3"
    output_file.write_bytes(b"fake audio")
    await fake_redis.hset(
        f"conversion:{conversion_id}",
        mapping={
            "status": "conversion_ready",
            "task_id": task_id,
            "output_filename": f"{task_id}.mp3",
        },
    )

    response = await async_client.get(f"/api/conversions/{conversion_id}/download")

    assert response.status_code == 200
    assert response.content == b"fake audio"


@pytest.mark.asyncio
async def test_download_rejects_traversal_output_filename(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    conversion_id = "conv-1"
    victim_dir = tmp_download_dir / "victim"
    victim_dir.mkdir()
    victim_file = victim_dir / "source.mp4"
    victim_file.write_bytes(b"sibling video")
    await fake_redis.hset(
        f"conversion:{conversion_id}",
        mapping={
            "status": "conversion_ready",
            "task_id": task_id,
            "output_filename": "../../../victim/source.mp4",
        },
    )

    response = await async_client.get(f"/api/conversions/{conversion_id}/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"
    assert response.content != b"sibling video"


@pytest.mark.asyncio
async def test_download_nul_output_filename_is_invalid_conversion_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_ready",
            "task_id": "task-1",
            "output_filename": "\x00",
        },
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_download_rejects_traversal_conversion_id(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    task_id = "task-1"
    task_dir = tmp_download_dir / task_id
    task_dir.mkdir()
    sibling_file = task_dir / "source.mp3"
    sibling_file.write_bytes(b"sibling audio")

    original_hgetall = fake_redis.hgetall

    async def reject_lookup(key: str):
        if key == "conversion:..":
            raise AssertionError("invalid route id reached Redis lookup")
        return await original_hgetall(key)

    fake_redis.hgetall = reject_lookup

    response = await async_client.get("/api/conversions/%2E%2E/download")

    assert response.status_code == 400
    assert response.content != b"sibling audio"


@pytest.mark.asyncio
async def test_download_rejects_traversal_task_id_from_redis(
    async_client,
    fake_redis,
    tmp_download_dir: Path,
) -> None:
    conversion_id = "conv-1"
    output_dir = tmp_download_dir / "task-1" / "outputs" / conversion_id
    output_dir.mkdir(parents=True)
    output_file = output_dir / "source.mp3"
    output_file.write_bytes(b"fake audio")
    await fake_redis.hset(
        f"conversion:{conversion_id}",
        mapping={
            "status": "conversion_ready",
            "task_id": "task-1/outputs/conv-1/../..",
            "output_filename": "source.mp3",
        },
    )

    response = await async_client.get(f"/api/conversions/{conversion_id}/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"
    assert response.content != b"fake audio"


@pytest.mark.asyncio
async def test_download_nul_task_id_from_redis_is_invalid_conversion_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={
            "status": "conversion_ready",
            "task_id": "\x00",
            "output_filename": "source.mp3",
        },
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_download_not_ready_conversion(async_client, fake_redis) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={"status": "conversion_processing", "task_id": "task-1"},
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_download_rejects_invalid_conversion_status_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={"status": "garbage", "task_id": "task-1"},
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_download_ready_conversion_missing_task_id_is_invalid_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={"status": "conversion_ready", "output_filename": "source.mp3"},
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"


@pytest.mark.asyncio
async def test_download_ready_conversion_missing_output_filename_is_invalid_state(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "conversion:conv-1",
        mapping={"status": "conversion_ready", "task_id": "task-1"},
    )

    response = await async_client.get("/api/conversions/conv-1/download")

    assert response.status_code == 500
    assert response.json()["detail"] == "Conversion state is invalid"
