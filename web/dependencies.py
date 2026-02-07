"""Shared FastAPI dependencies for the web layer."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from orchestration.project_state import ProjectState


def get_projects_dir(request: Request) -> Path:
    """Return the projects directory from app state."""
    return Path(request.app.state.projects_dir)


def get_docs_dir(request: Request) -> Path:
    """Return the constitutional docs directory from app state."""
    return Path(request.app.state.docs_dir)


def get_project(project_id: str, request: Request) -> ProjectState:
    """Load a project by ID, raising 404 if not found."""
    projects_dir = get_projects_dir(request)
    try:
        return ProjectState.load(project_id, projects_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


def get_ws_manager(request: Request):
    """Return the WebSocket manager from app state."""
    return request.app.state.ws_manager
