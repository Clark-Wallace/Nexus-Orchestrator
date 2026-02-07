"""Cost reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from orchestration.cost_tracker import (
    aggregate_costs_by_model,
    aggregate_costs_by_provider,
    aggregate_costs_by_role,
    aggregate_costs_by_tier,
    format_cost_report,
    total_project_cost,
)
from web.dependencies import get_project, get_projects_dir
from web.schemas import CostReportResponse

router = APIRouter(tags=["costs"])


@router.get("/projects/{project_id}/costs", response_model=CostReportResponse)
async def get_cost_report(project_id: str, request: Request):
    """Get cost report with formatted text and structured breakdown."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    report_text = format_cost_report(project_id, str(projects_dir))
    cost = total_project_cost(project_id, str(projects_dir))

    breakdown = {
        "by_tier": aggregate_costs_by_tier(project_id, str(projects_dir)),
        "by_provider": aggregate_costs_by_provider(project_id, str(projects_dir)),
        "by_role": aggregate_costs_by_role(project_id, str(projects_dir)),
        "by_model": aggregate_costs_by_model(project_id, str(projects_dir)),
    }

    return CostReportResponse(
        report_text=report_text,
        total_cost=cost,
        breakdown=breakdown,
    )
