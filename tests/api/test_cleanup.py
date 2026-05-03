import os
import time
from pathlib import Path

import pytest

from yt_downloader.services.cleanup import cleanup_expired_files


def test_cleanup_removes_expired_files_and_empty_directories(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    old_dir = download_dir / "old-task"
    old_dir.mkdir()
    old_file = old_dir / "source.mp4"
    old_file.write_text("old")
    old_time = time.time() - (25 * 3600)
    os.utime(old_dir, (old_time, old_time))
    os.utime(old_file, (old_time, old_time))

    new_dir = download_dir / "new-task"
    new_dir.mkdir()
    (new_dir / "source.mp4").write_text("new")

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)

    assert not old_dir.exists()
    assert new_dir.exists()


def test_cleanup_preserves_fresh_nested_output_in_old_task_dir(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    task_dir = download_dir / "task-with-new-output"
    output_dir = task_dir / "outputs" / "conversion-1"
    output_dir.mkdir(parents=True)
    output_file = output_dir / "source.mp3"
    output_file.write_text("fresh output")

    old_time = time.time() - (25 * 3600)
    os.utime(task_dir, (old_time, old_time))

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)

    assert task_dir.exists()
    assert output_file.exists()


def test_cleanup_preserves_fresh_empty_directories(tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    task_dir = download_dir / "fresh-task"
    output_dir = task_dir / "outputs" / "conversion-1"
    output_dir.mkdir(parents=True)

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)

    assert task_dir.exists()
    assert output_dir.exists()


def test_cleanup_ignores_file_disappearing_before_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    old_file = download_dir / "source.mp4"
    old_file.write_text("old")
    old_time = time.time() - (25 * 3600)
    os.utime(old_file, (old_time, old_time))

    original_stat = Path.stat
    stat_calls = 0

    def disappearing_stat(self: Path, *args, **kwargs):
        nonlocal stat_calls
        if self == old_file:
            stat_calls += 1
            if stat_calls == 2:
                old_file.unlink(missing_ok=True)
                raise FileNotFoundError(str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", disappearing_stat)

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)


def test_cleanup_ignores_file_disappearing_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    old_file = download_dir / "source.mp4"
    old_file.write_text("old")
    old_time = time.time() - (25 * 3600)
    os.utime(old_file, (old_time, old_time))

    original_unlink = Path.unlink

    def disappearing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == old_file:
            original_unlink(self, missing_ok=True)
            if missing_ok:
                return
            raise FileNotFoundError(str(self))
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", disappearing_unlink)

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)


def test_cleanup_ignores_directory_disappearing_before_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    old_dir = download_dir / "old-task"
    old_dir.mkdir()
    old_time = time.time() - (25 * 3600)
    os.utime(old_dir, (old_time, old_time))

    original_rmdir = Path.rmdir
    original_stat = Path.stat
    stat_calls = 0

    def disappearing_stat(self: Path, *args, **kwargs):
        nonlocal stat_calls
        if self == old_dir:
            stat_calls += 1
            if stat_calls == 5:
                original_rmdir(self)
                raise FileNotFoundError(str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", disappearing_stat)

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)


def test_cleanup_ignores_directory_disappearing_before_rmdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    old_dir = download_dir / "old-task"
    old_dir.mkdir()
    old_time = time.time() - (25 * 3600)
    os.utime(old_dir, (old_time, old_time))

    original_rmdir = Path.rmdir

    def disappearing_rmdir(self: Path) -> None:
        if self == old_dir:
            original_rmdir(self)
            raise FileNotFoundError(str(self))
        original_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", disappearing_rmdir)

    cleanup_expired_files(download_dir=download_dir, ttl_hours=24)


def test_cleanup_ignores_missing_download_dir(tmp_path: Path) -> None:
    cleanup_expired_files(download_dir=tmp_path / "missing", ttl_hours=24)
