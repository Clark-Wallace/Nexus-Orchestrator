"""Artifact endpoints — list and detail with lineage."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from web.dependencies import get_project, get_projects_dir
from web.schemas import ArtifactDetail, ArtifactSummary

router = APIRouter(tags=["artifacts"])


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactSummary])
async def list_artifacts(project_id: str, request: Request):
    """List all registered artifacts for a project."""
    project = get_project(project_id, request)

    summaries: list[ArtifactSummary] = []
    for file_path, artifact in project.artifacts.items():
        summaries.append(ArtifactSummary(
            artifact_id=artifact.artifact_id,
            file_path=artifact.file_path,
            task_id=artifact.task_id or "",
            tier=artifact.tier,
            subsystem=artifact.subsystem or "",
        ))
    return summaries


@router.get("/projects/{project_id}/artifacts/{artifact_id}")
async def get_artifact_detail(project_id: str, artifact_id: str, request: Request):
    """Get a single artifact's detail including lineage chain."""
    project = get_project(project_id, request)

    for file_path, artifact in project.artifacts.items():
        if artifact.artifact_id == artifact_id:
            return ArtifactDetail(
                data=artifact.to_dict(),
                lineage=artifact.lineage or [],
            )

    raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
