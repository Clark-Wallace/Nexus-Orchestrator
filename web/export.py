"""Project archive export — pure functions with no FastAPI dependency.

Usable from both CLI (cmd_export) and web (export route).
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path


def create_project_archive(
    project_id: str, projects_dir: str | Path
) -> tuple[BytesIO, str]:
    """Zip the entire project directory into an in-memory archive.

    Returns (BytesIO with zip data, suggested filename).
    Raises FileNotFoundError if the project directory doesn't exist.
    """
    project_dir = Path(projects_dir) / project_id
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(project_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(project_dir)
                zf.write(file_path, arcname)

    buf.seek(0)
    filename = f"{project_id}_export.zip"
    return buf, filename


def list_project_files(
    project_id: str, projects_dir: str | Path
) -> list[dict]:
    """List all files in a project directory with relative paths and sizes.

    Returns list of {"path": str, "size": int} dicts.
    Raises FileNotFoundError if the project directory doesn't exist.
    """
    project_dir = Path(projects_dir) / project_id
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    files: list[dict] = []
    for file_path in sorted(project_dir.rglob("*")):
        if file_path.is_file():
            files.append({
                "path": str(file_path.relative_to(project_dir)),
                "size": file_path.stat().st_size,
            })
    return files
