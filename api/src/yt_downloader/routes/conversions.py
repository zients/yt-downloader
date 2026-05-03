from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from yt_downloader.background import schedule_background_task
from yt_downloader.config import settings
from yt_downloader.models.schemas import (
    ConversionCreateRequest,
    ConversionCreateResponse,
    ConversionStatusResponse,
)
from yt_downloader.redis_client import get_redis
from yt_downloader.services.converter import convert_file
from yt_downloader.services.paths import safe_path_under
from yt_downloader.services.redis_state import write_hash_state

router = APIRouter(tags=["conversions"])

SOURCE_STATUSES = {"source_pending", "source_processing", "source_ready", "failed"}
CONVERSION_STATUSES = {
    "conversion_pending",
    "conversion_processing",
    "conversion_ready",
    "failed",
}


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


def _invalid_conversion_state() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Conversion state is invalid",
    )


def _invalid_task_state() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Task state is invalid",
    )


def _parse_conversion_status(
    conversion_id: str,
    data: dict[str, str],
) -> ConversionStatusResponse:
    try:
        return ConversionStatusResponse(
            conversion_id=conversion_id,
            task_id=_simple_state_identifier(data["task_id"]),
            status=data["status"],
            progress=_optional_int(data.get("progress")),
            message=data.get("message") or None,
            download_url=data.get("download_url") or None,
            error=data.get("error") or None,
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise _invalid_conversion_state() from exc


def _safe_download_path(*parts: str) -> Path:
    try:
        return safe_path_under(settings.download_dir, *parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download path",
        ) from exc


def _is_simple_path_component(value: str) -> bool:
    return not (
        value in {"", ".", ".."}
        or "\x00" in value
        or PurePosixPath(value).name != value
        or PureWindowsPath(value).name != value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    )


def _simple_task_state_filename(filename: str) -> str:
    if not _is_simple_path_component(filename):
        raise _invalid_task_state()
    return filename


def _simple_conversion_state_filename(filename: str) -> str:
    if not _is_simple_path_component(filename):
        raise _invalid_conversion_state()
    return filename


def _simple_identifier(identifier: str) -> str:
    if not _is_simple_path_component(identifier):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid identifier",
        )
    return identifier


def _simple_state_identifier(identifier: str) -> str:
    if not _is_simple_path_component(identifier):
        raise _invalid_conversion_state()
    return identifier


@router.post(
    "/tasks/{task_id}/conversions",
    response_model=ConversionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversion(
    task_id: str,
    payload: ConversionCreateRequest,
    request: Request,
) -> ConversionCreateResponse:
    task_id = _simple_identifier(task_id)
    redis_client = await _redis_client(request)
    task_data = await redis_client.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task_status = task_data.get("status")
    if task_status not in SOURCE_STATUSES:
        raise _invalid_task_state()
    if task_status != "source_ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source is not ready",
        )

    source_filename = task_data.get("source_filename")
    if not source_filename:
        raise _invalid_task_state()
    source_filename = _simple_task_state_filename(source_filename)
    source_path = _safe_download_path(task_id, source_filename)
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source file not found",
        )

    conversion_id = str(uuid4())
    await write_hash_state(
        redis_client,
        f"conversion:{conversion_id}",
        {
            "status": "conversion_pending",
            "task_id": task_id,
            "progress": 0,
        },
        _ttl_seconds(),
    )
    schedule_background_task(
        request.app,
        convert_file(
            conversion_id=conversion_id,
            task_id=task_id,
            source_path=source_path,
            target_format=payload.format,
            quality=payload.quality,
            redis_client=redis_client,
            download_dir=settings.download_dir,
        )
    )

    return ConversionCreateResponse(
        conversion_id=conversion_id,
        task_id=task_id,
        status="conversion_pending",
    )


@router.get("/conversions/{conversion_id}", response_model=ConversionStatusResponse)
async def get_conversion(
    conversion_id: str,
    request: Request,
) -> ConversionStatusResponse:
    conversion_id = _simple_identifier(conversion_id)
    redis_client = await _redis_client(request)
    data = await redis_client.hgetall(f"conversion:{conversion_id}")
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversion not found",
        )

    return _parse_conversion_status(conversion_id, data)


@router.get("/conversions/{conversion_id}/download")
async def download_conversion(conversion_id: str, request: Request) -> FileResponse:
    conversion_id = _simple_identifier(conversion_id)
    redis_client = await _redis_client(request)
    data = await redis_client.hgetall(f"conversion:{conversion_id}")
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversion not found",
        )
    conversion_status = data.get("status")
    if conversion_status not in CONVERSION_STATUSES:
        raise _invalid_conversion_state()
    if conversion_status != "conversion_ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversion is not ready",
        )

    task_id = data.get("task_id")
    output_filename = data.get("output_filename")
    if not task_id or not output_filename:
        raise _invalid_conversion_state()
    task_id = _simple_state_identifier(task_id)
    output_filename = _simple_conversion_state_filename(output_filename)

    output_path = _safe_download_path(
        task_id,
        "outputs",
        conversion_id,
        output_filename,
    )
    if not output_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output file not found",
        )

    return FileResponse(output_path, filename=output_path.name)
