import asyncio
import json
from collections.abc import Callable
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


def _source_filename(info: dict[str, Any], task_id: str) -> str:
    requested_downloads = info.get("requested_downloads") or []
    if requested_downloads:
        filepath = requested_downloads[0].get("filepath")
        if filepath:
            suffix = Path(filepath).suffix or ".mp4"
            return f"{task_id}{suffix}"

    filename = info.get("_filename")
    if filename:
        suffix = Path(filename).suffix or ".mp4"
        return f"{task_id}{suffix}"

    return f"{task_id}.mp4"


def _progress_percent(progress: dict[str, Any]) -> int | None:
    downloaded_bytes = progress.get("downloaded_bytes")
    total_bytes = progress.get("total_bytes") or progress.get("total_bytes_estimate")

    try:
        downloaded = float(downloaded_bytes)
        total = float(total_bytes)
    except (TypeError, ValueError):
        return None

    if downloaded < 0 or total <= 0:
        return None

    return min(99, max(0, int((downloaded / total) * 100)))


def _download(
    url: str,
    task_dir: Path,
    task_id: str,
    progress_callback: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    task_dir.mkdir(parents=True, exist_ok=True)
    last_progress = 0

    def progress_hook(progress: dict[str, Any]) -> None:
        nonlocal last_progress

        if progress.get("status") != "downloading" or progress_callback is None:
            return

        percent = _progress_percent(progress)
        if percent is None or percent == last_progress:
            return

        progress_callback(percent)
        last_progress = percent

    options = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "outtmpl": str(task_dir / f"{task_id}.%(ext)s"),
        "progress_hooks": [progress_hook],
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
    loop = asyncio.get_running_loop()

    def persist_source_progress(progress: int) -> None:
        future = asyncio.run_coroutine_threadsafe(
            write_hash_state(
                redis_client,
                task_key,
                {
                    "status": "source_processing",
                    "progress": progress,
                },
                _ttl_seconds(),
            ),
            loop,
        )
        future.result()

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
        info = await asyncio.to_thread(
            _download,
            url,
            task_dir,
            task_id,
            persist_source_progress,
        )
        await write_hash_state(
            redis_client,
            task_key,
            {
                "status": "source_ready",
                "title": info.get("title") or "",
                "thumbnail": info.get("thumbnail") or "",
                "source_filename": _source_filename(info, task_id),
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
