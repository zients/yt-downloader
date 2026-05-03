import asyncio
import math
import subprocess
import threading
from collections.abc import Callable
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


def _parse_ffprobe_duration(stdout: str) -> float | None:
    try:
        duration = float(stdout.strip())
    except ValueError:
        return None

    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def _probe_duration(source_path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    return _parse_ffprobe_duration(result.stdout)


def _parse_ffmpeg_time(value: str) -> float | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None

    return (hours * 3600) + (minutes * 60) + seconds


def _progress_percent_from_ffmpeg_fields(
    fields: dict[str, str],
    duration_seconds: float | None,
) -> int | None:
    if duration_seconds is None or duration_seconds <= 0:
        return None

    elapsed_seconds: float | None = None
    for key in ("out_time_ms", "out_time_us"):
        if key not in fields:
            continue
        try:
            elapsed_seconds = float(fields[key]) / 1_000_000
        except ValueError:
            return None
        break

    if elapsed_seconds is None and "out_time" in fields:
        elapsed_seconds = _parse_ffmpeg_time(fields["out_time"])

    if elapsed_seconds is None:
        return None

    return min(99, max(0, int((elapsed_seconds / duration_seconds) * 100)))


def _with_progress_flags(args: list[str]) -> list[str]:
    return [*args[:-1], "-progress", "pipe:1", "-nostats", args[-1]]


def _drain_process_stream(stream: Any, lines: list[str]) -> None:
    try:
        for line in stream:
            lines.append(line)
    except Exception as exc:
        lines.append(str(exc))


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_ffmpeg(
    source_path: Path,
    output_path: Path,
    target_format: str,
    quality: str | None,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(source_path)
    args = _with_progress_flags(build_ffmpeg_args(source_path, output_path, target_format, quality))
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: list[str] = []
    stderr_thread: threading.Thread | None = None
    if process.stderr is not None:
        stderr_thread = threading.Thread(
            target=_drain_process_stream,
            args=(process.stderr, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()

    fields: dict[str, str] = {}
    last_progress = 0

    try:
        if process.stdout is not None:
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if not separator:
                    continue
                if key in {"out_time_ms", "out_time_us", "out_time"}:
                    fields.pop("out_time_ms", None)
                    fields.pop("out_time_us", None)
                    fields.pop("out_time", None)
                fields[key] = value
                percent = _progress_percent_from_ffmpeg_fields(fields, duration)
                if (
                    progress_callback is not None
                    and percent is not None
                    and percent != last_progress
                ):
                    progress_callback(percent)
                    last_progress = percent

        returncode = process.wait()
    except Exception:
        _terminate_process(process)
        raise
    finally:
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)

    if returncode != 0:
        message = "".join(stderr_lines).strip() or "ffmpeg failed"
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
    loop = asyncio.get_running_loop()

    def persist_conversion_progress(progress: int) -> None:
        future = asyncio.run_coroutine_threadsafe(
            write_hash_state(
                redis_client,
                conversion_key,
                {
                    "status": "conversion_processing",
                    "task_id": task_id,
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
            f"{task_id}.{target_format}",
        )
        async with _conversion_semaphore:
            output_path = await asyncio.to_thread(
                _run_ffmpeg,
                source_path,
                output_path,
                target_format,
                quality,
                persist_conversion_progress,
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
