import asyncio
import subprocess
from pathlib import Path
from typing import Any

from yt_downloader.config import settings
from yt_downloader.models.schemas import AUDIO_FORMATS
from yt_downloader.services.paths import safe_path_under
from yt_downloader.services.redis_state import (
    StatePersistenceError,
    write_failure_state,
    write_hash_state,
)

_conversion_semaphore = asyncio.Semaphore(settings.max_concurrent_conversions)

_AUDIO_CODECS = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "flac": "flac",
    "aac": "aac",
    "ogg": "libvorbis",
    "m4a": "aac",
}

_VIDEO_CODECS = {
    "mp4": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "mkv": ("libx264", "aac"),
    "avi": ("mpeg4", "libmp3lame"),
    "mov": ("libx264", "aac"),
}


def _ttl_seconds() -> int:
    return settings.file_ttl_hours * 3600


def build_ffmpeg_args(
    source_path: Path,
    output_path: Path,
    target_format: str,
    quality: str | None,
) -> list[str]:
    args = ["ffmpeg", "-y", "-i", str(source_path)]

    if target_format in AUDIO_FORMATS:
        return [
            *args,
            "-vn",
            "-codec:a",
            _AUDIO_CODECS[target_format],
            str(output_path),
        ]

    video_codec, audio_codec = _VIDEO_CODECS[target_format]
    video_args = ["-codec:v", video_codec, "-codec:a", audio_codec]
    if quality is not None:
        video_args.extend(["-vf", f"scale=-2:{quality.removesuffix('p')}"])

    return [*args, *video_args, str(output_path)]


def _run_ffmpeg(
    source_path: Path,
    output_path: Path,
    target_format: str,
    quality: str | None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = build_ffmpeg_args(source_path, output_path, target_format, quality)
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or "ffmpeg failed"
        raise RuntimeError(message)
    return output_path


async def convert_file(
    *,
    conversion_id: str,
    task_id: str,
    source_path: Path,
    target_format: str,
    quality: str | None,
    redis_client: Any,
    download_dir: Path,
) -> None:
    conversion_key = f"conversion:{conversion_id}"

    try:
        await write_hash_state(
            redis_client,
            conversion_key,
            {
                "status": "conversion_processing",
                "task_id": task_id,
                "progress": 0,
            },
            _ttl_seconds(),
        )
        output_path = safe_path_under(
            download_dir,
            task_id,
            "outputs",
            conversion_id,
            f"{source_path.stem}.{target_format}",
        )
        async with _conversion_semaphore:
            output_path = await asyncio.to_thread(
                _run_ffmpeg,
                source_path,
                output_path,
                target_format,
                quality,
            )

        await write_hash_state(
            redis_client,
            conversion_key,
            {
                "status": "conversion_ready",
                "task_id": task_id,
                "progress": 100,
                "output_filename": output_path.name,
                "download_url": f"/api/conversions/{conversion_id}/download",
            },
            _ttl_seconds(),
        )
    except Exception as exc:
        persisted = await write_failure_state(
            redis_client,
            conversion_key,
            {
                "status": "failed",
                "task_id": task_id,
                "error": str(exc),
            },
            _ttl_seconds(),
        )
        if not persisted:
            raise RuntimeError("Failed to persist conversion failure state") from exc
        if isinstance(exc, StatePersistenceError):
            raise RuntimeError("Failed to persist conversion state") from exc
