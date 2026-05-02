import asyncio
import json
from pathlib import Path
from typing import Any

import yt_dlp

from yt_downloader.config import settings
from yt_downloader.services.paths import safe_path_under
from yt_downloader.services.redis_state import (
    StatePersistenceError,
    write_failure_state,
    write_hash_state,
)


def _ttl_seconds() -> int:
    return settings.file_ttl_hours * 3600


def _source_filename(info: dict[str, Any]) -> str:
    requested_downloads = info.get("requested_downloads") or []
    if requested_downloads:
        filepath = requested_downloads[0].get("filepath")
        if filepath:
            return Path(filepath).name

    filename = info.get("_filename")
    if filename:
        return Path(filename).name

    return "source.mp4"


def _download(url: str, task_dir: Path) -> dict[str, Any]:
    task_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "outtmpl": str(task_dir / "source.%(ext)s"),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=True)


async def download_video(
    task_id: str,
    url: str,
    redis_client: Any,
    download_dir: Path,
) -> None:
    task_key = f"task:{task_id}"

    try:
        await write_hash_state(
            redis_client,
            task_key,
            {
                "status": "source_processing",
                "progress": 0,
            },
            _ttl_seconds(),
        )
        task_dir = safe_path_under(download_dir, task_id)
        info = await asyncio.to_thread(_download, url, task_dir)
        await write_hash_state(
            redis_client,
            task_key,
            {
                "status": "source_ready",
                "title": info.get("title") or "",
                "thumbnail": info.get("thumbnail") or "",
                "source_filename": _source_filename(info),
                "progress": 100,
                "output_presets": json.dumps(
                    {
                        "video": settings.video_presets,
                        "audio": settings.audio_presets,
                    }
                ),
            },
            _ttl_seconds(),
        )
    except Exception as exc:
        persisted = await write_failure_state(
            redis_client,
            task_key,
            {
                "status": "failed",
                "error": str(exc),
            },
            _ttl_seconds(),
        )
        if not persisted:
            raise RuntimeError("Failed to persist task failure state") from exc
        if isinstance(exc, StatePersistenceError):
            raise RuntimeError("Failed to persist task state") from exc
