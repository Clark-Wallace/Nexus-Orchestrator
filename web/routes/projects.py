"""Project endpoints — list, create, get, status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestration.models import VisionContract, VisionValidationError
from orchestration.project_state import ProjectState
from web.dependencies import get_project, get_projects_dir
from web.schemas import ProjectCreateRequest, ProjectDetail, ProjectSummary

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(request: Request):
    """List all projects with summary info."""
    projects_dir = get_projects_dir(request)
    ids = ProjectState.list_projects(projects_dir)
    summaries: list[ProjectSummary] = []
    for pid in ids:
        try:
            p = ProjectState.load(pid, projects_dir)
            health = p.health.to_dict() if p.health else {}
            summaries.append(ProjectSummary(
                project_id=p.project_id,
                project_name=p.project_name,
                current_phase=p.current_phase,
                current_tier=p.current_tier,
                created_at=p.created_at,
                health=health,
            ))
        except Exception:
            continue
    return summaries


@router.post("/projects", response_model=ProjectDetail, status_code=201)
async def create_project(body: ProjectCreateRequest, request: Request):
    """Create a new project from a Vision Contract markdown string."""
    projects_dir = get_projects_dir(request)
    strict = not body.relaxed

    try:
        vision = VisionContract.from_markdown(body.vision_markdown, strict=strict)
    except VisionValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not vision.project_name:
        vision.project_name = "Untitled Project"

    project = ProjectState(
        project_name=vision.project_name,
        vision_contract=vision,
        current_tier=0,
        current_phase="vision_intake",
    )
    project.save(projects_dir)

    return ProjectDetail(data=project.to_dict())


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project_detail(project_id: str, request: Request):
    """Get full project state."""
    project = get_project(project_id, request)
    return ProjectDetail(data=project.to_dict())


@router.get("/projects/{project_id}/status")
async def get_project_status(project_id: str, request: Request):
    """Get project phase, tier, and health summary."""
    project = get_project(project_id, request)
    health = project.health.to_dict() if project.health else {}
    return {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "current_phase": project.current_phase,
        "current_tier": project.current_tier,
        "health": health,
        "summary": project.status_summary(),
    }
