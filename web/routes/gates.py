"""Gate endpoints — list, detail, respond."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from orchestration.gate_manager import GateManager
from orchestration.models import GateResponse, GateResponseType
from web.dependencies import get_project, get_projects_dir, get_ws_manager
from web.schemas import GateDetail, GateResponseInput, GateSummary

router = APIRouter(tags=["gates"])


@router.get("/projects/{project_id}/gates", response_model=list[GateSummary])
async def list_gates(project_id: str, request: Request):
    """List all gates for a project."""
    # Verify project exists
    get_project(project_id, request)

    projects_dir = get_projects_dir(request)
    gate_manager = GateManager(projects_dir)
    gates = gate_manager.list_gates(project_id)

    return [
        GateSummary(
            gate_id=g.gate_id,
            gate_type=g.gate_type,
            status=g.status,
            summary=g.summary,
            phase=g.phase,
        )
        for g in gates
    ]


@router.get("/projects/{project_id}/gates/{gate_id}", response_model=GateDetail)
async def get_gate_detail(project_id: str, gate_id: str, request: Request):
    """Get full gate detail."""
    project = get_project(project_id, request)

    for g in project.gates:
        if g.gate_id == gate_id:
            return GateDetail(data=g.to_dict())

    raise HTTPException(status_code=404, detail=f"Gate '{gate_id}' not found")


@router.post("/projects/{project_id}/gates/{gate_id}")
async def respond_to_gate(
    project_id: str,
    gate_id: str,
    body: GateResponseInput,
    request: Request,
):
    """Respond to a pending gate (approve, reject, modify, etc.)."""
    projects_dir = get_projects_dir(request)
    project = get_project(project_id, request)
    gate_manager = GateManager(projects_dir)

    # Build GateResponse from input
    response = _build_gate_response(body)

    try:
        gate = gate_manager.respond_to_gate(project, gate_id, response)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    project.save(projects_dir)

    # Broadcast gate event via WebSocket
    ws_manager = get_ws_manager(request)
    await ws_manager.broadcast(project_id, "gate_responded", {
        "gate_id": gate.gate_id,
        "status": gate.status,
        "response_type": body.response_type,
    })

    return {"gate_id": gate.gate_id, "status": gate.status}


def _build_gate_response(body: GateResponseInput) -> GateResponse:
    """Convert API input to a GateResponse model."""
    rt = body.response_type

    if rt == GateResponseType.CHOOSE.value:
        return GateResponse(
            response_type=rt,
            chosen_option=body.chosen_option,
        )
    elif rt == GateResponseType.CHOOSE_WITH_MODIFICATIONS.value:
        return GateResponse(
            response_type=rt,
            chosen_option=body.chosen_option,
            modifications=body.modifications,
        )
    elif rt == GateResponseType.COMBINE.value:
        return GateResponse(
            response_type=rt,
            combine_instructions=body.combine_instructions,
        )
    elif rt == GateResponseType.REVISE_AND_PROCEED.value:
        return GateResponse(
            response_type=rt,
            revision_feedback=body.revision_feedback,
        )
    elif rt == GateResponseType.EXPLORE_DIFFERENTLY.value:
        return GateResponse(
            response_type=rt,
            redirect_instructions=body.redirect_instructions,
        )
    elif rt == GateResponseType.REJECT.value:
        return GateResponse(
            response_type=rt,
            rejection_reason=body.feedback,
        )
    else:
        # Pass through as-is
        return GateResponse(response_type=rt)
