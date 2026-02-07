"""Lineage and decisions endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from orchestration.lineage import load_artifact_lineage, load_decisions
from web.dependencies import get_project, get_projects_dir
from web.schemas import DecisionEntry, LineageEntry

router = APIRouter(tags=["lineage"])


@router.get("/projects/{project_id}/lineage", response_model=list[LineageEntry])
async def get_lineage(project_id: str, request: Request):
    """Get artifact lineage data (all artifacts with their lineage chains)."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    artifacts = load_artifact_lineage(project_id, projects_dir)

    return [
        LineageEntry(
            artifact_id=a.artifact_id,
            file_path=a.file_path,
            lineage=a.lineage or [],
            produced_by=a.produced_by or "",
            task_id=a.task_id or "",
        )
        for a in artifacts
    ]


@router.get("/projects/{project_id}/decisions", response_model=list[DecisionEntry])
async def get_decisions(project_id: str, request: Request):
    """Get all recorded decisions for a project."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    decisions = load_decisions(project_id, projects_dir)

    return [
        DecisionEntry(
            decision_id=d.decision_id,
            timestamp=d.timestamp,
            decision_type=d.decision_type,
            made_by=d.made_by,
            description=d.description,
            rationale=d.rationale,
        )
        for d in decisions
    ]
