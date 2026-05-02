import os
import stat
import time
from pathlib import Path


def _stat_path(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def cleanup_expired_files(*, download_dir: Path, ttl_hours: int) -> None:
    if not download_dir.exists():
        return

    cutoff = time.time() - (ttl_hours * 3600)
    directory_mtimes = {}

    for path in download_dir.rglob("*"):
        path_stat = _stat_path(path)
        if path_stat is not None and stat.S_ISDIR(path_stat.st_mode):
            directory_mtimes[path] = path_stat.st_mtime

    for path in download_dir.rglob("*"):
        path_stat = _stat_path(path)
        if (
            path_stat is not None
            and stat.S_ISREG(path_stat.st_mode)
            and path_stat.st_mtime < cutoff
        ):
            path.unlink(missing_ok=True)

    directories = []
    for path in download_dir.rglob("*"):
        path_stat = _stat_path(path)
        if path_stat is not None and stat.S_ISDIR(path_stat.st_mode):
            directories.append(path)

    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        if directory in directory_mtimes:
            directory_mtime = directory_mtimes[directory]
        else:
            directory_stat = _stat_path(directory)
            if directory_stat is None:
                continue
            directory_mtime = directory_stat.st_mtime

        if directory_mtime >= cutoff:
            continue
        try:
            directory.rmdir()
        except OSError:
            pass
