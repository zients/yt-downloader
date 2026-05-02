import json
from json import JSONDecodeError
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from yt_downloader.background import schedule_background_task
from yt_downloader.config import settings
from yt_downloader.models.schemas import (
    TaskCreateRequest,
    TaskCreateResponse,
    TaskStatusResponse,
)
from yt_downloader.redis_client import get_redis
from yt_downloader.services.downloader import download_video
from yt_downloader.services.redis_state import write_hash_state

router = APIRouter(tags=["tasks"])


def _ttl_seconds() -> int:
    return settings.file_ttl_hours * 3600


async def _redis_client(request: Request) -> Any:
    if hasattr(request.app.state, "redis"):
        return request.app.state.redis
    return await get_redis()


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _invalid_task_state() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Task state is invalid",
    )


def _is_simple_path_component(value: str) -> bool:
    return not (
        value in {"", ".", ".."}
        or "\x00" in value
        or PurePosixPath(value).name != value
        or PureWindowsPath(value).name != value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    )


def _simple_identifier(identifier: str) -> str:
    if not _is_simple_path_component(identifier):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid identifier",
        )
    return identifier


def _parse_task_status(task_id: str, data: dict[str, str]) -> TaskStatusResponse:
    try:
        output_presets = None
        if data.get("output_presets"):
            output_presets = json.loads(data["output_presets"])

        return TaskStatusResponse(
            task_id=task_id,
            status=data["status"],
            title=data.get("title") or None,
            thumbnail=data.get("thumbnail") or None,
            progress=_optional_int(data.get("progress")),
            message=data.get("message") or None,
            output_presets=output_presets,
            error=data.get("error") or None,
        )
    except (KeyError, JSONDecodeError, ValidationError, ValueError) as exc:
        raise _invalid_task_state() from exc


@router.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(payload: TaskCreateRequest, request: Request) -> TaskCreateResponse:
    redis_client = await _redis_client(request)
    task_id = str(uuid4())

    await write_hash_state(
        redis_client,
        f"task:{task_id}",
        {
            "status": "source_pending",
            "progress": 0,
        },
        _ttl_seconds(),
    )
    schedule_background_task(
        request.app,
        download_video(task_id, str(payload.url), redis_client, settings.download_dir)
    )

    return TaskCreateResponse(task_id=task_id, status="source_pending")


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str, request: Request) -> TaskStatusResponse:
    task_id = _simple_identifier(task_id)
    redis_client = await _redis_client(request)
    data = await redis_client.hgetall(f"task:{task_id}")
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return _parse_task_status(task_id, data)
