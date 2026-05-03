import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI

from yt_downloader.main import create_app


@pytest_asyncio.fixture
async def app(fake_redis) -> FastAPI:
    application = create_app()
    application.state.redis = fake_redis
    return application


@pytest.mark.asyncio
async def test_create_task_returns_source_pending(async_client) -> None:
    with patch("yt_downloader.routes.tasks.download_video", new_callable=AsyncMock):
        response = await async_client.post(
            "/api/tasks",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "source_pending"


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_url(async_client) -> None:
    response = await async_client.post("/api/tasks", json={"url": "https://example.com"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_task_source_ready(async_client, fake_redis) -> None:
    task_id = "task-1"
    await fake_redis.hset(
        f"task:{task_id}",
        mapping={
            "status": "source_ready",
            "title": "Example",
            "thumbnail": "https://img.youtube.com/vi/example/0.jpg",
            "progress": "100",
            "output_presets": json.dumps(
                {
                    "video": [{"format": "mp4", "quality": "1080p"}],
                    "audio": [{"format": "mp3"}],
                }
            ),
        },
    )

    response = await async_client.get(f"/api/tasks/{task_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "source_ready"
    assert body["output_presets"]["video"][0]["format"] == "mp4"


@pytest.mark.asyncio
async def test_get_task_rejects_invalid_route_id(async_client, fake_redis) -> None:
    await fake_redis.hset(
        "task:..",
        mapping={"status": "source_ready", "progress": "100"},
    )

    response = await async_client.get("/api/tasks/%2E%2E")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_task_rejects_nul_route_id(async_client, fake_redis) -> None:
    await fake_redis.hset(
        "task:\x00",
        mapping={"status": "source_ready", "progress": "100"},
    )

    response = await async_client.get("/api/tasks/%00")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_task_invalid_progress_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "task:task-1",
        mapping={"status": "source_processing", "progress": "nan"},
    )

    response = await async_client.get("/api/tasks/task-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"


@pytest.mark.asyncio
async def test_get_task_invalid_output_presets_json_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "task:task-1",
        mapping={
            "status": "source_ready",
            "progress": "100",
            "output_presets": "{",
        },
    )

    response = await async_client.get("/api/tasks/task-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"


@pytest.mark.asyncio
async def test_get_task_invalid_output_preset_returns_controlled_error(
    async_client,
    fake_redis,
) -> None:
    await fake_redis.hset(
        "task:task-1",
        mapping={
            "status": "source_ready",
            "progress": "100",
            "output_presets": json.dumps(
                {
                    "video": [{"format": "mkv", "quality": "480p"}],
                    "audio": [{"format": "mp3"}],
                }
            ),
        },
    )

    response = await async_client.get("/api/tasks/task-1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Task state is invalid"


@pytest.mark.asyncio
async def test_get_task_not_found(async_client) -> None:
    response = await async_client.get("/api/tasks/missing")
    assert response.status_code == 404
