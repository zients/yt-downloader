from pathlib import Path


def safe_path_under(root: Path, *parts: str) -> Path:
    root_path = root.resolve()
    candidate = root_path.joinpath(*parts).resolve()

    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Path escapes download directory") from exc

    return candidate
