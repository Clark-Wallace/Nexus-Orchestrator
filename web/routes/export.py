"""Export endpoints — download project archive and info."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from web.dependencies import get_project, get_projects_dir
from web.export import create_project_archive, list_project_files
from web.schemas import ExportInfo

router = APIRouter(tags=["export"])


@router.get("/projects/{project_id}/export")
async def download_export(project_id: str, request: Request):
    """Download the project as a zip archive."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    try:
        buf, filename = create_project_archive(project_id, projects_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project directory not found")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/projects/{project_id}/export/info", response_model=ExportInfo)
async def export_info(project_id: str, request: Request):
    """Get info about what would be exported (file list, sizes)."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    try:
        files = list_project_files(project_id, projects_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project directory not found")

    total_size = sum(f["size"] for f in files)
    return ExportInfo(
        file_count=len(files),
        total_size=total_size,
        files=files,
    )
