"""Pydantic v2 request/response schemas for the web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Project schemas
# ---------------------------------------------------------------------------

class ProjectSummary(BaseModel):
    project_id: str
    project_name: str
    current_phase: str
    current_tier: int
    created_at: str
    health: dict[str, Any] = {}


class ProjectDetail(BaseModel):
    """Full project state — wraps the dict from project.to_dict()."""
    data: dict[str, Any]


class ProjectCreateRequest(BaseModel):
    vision_markdown: str
    relaxed: bool = False


# ---------------------------------------------------------------------------
# Gate schemas
# ---------------------------------------------------------------------------

class GateSummary(BaseModel):
    gate_id: str
    gate_type: str
    status: str
    summary: str
    phase: str = ""


class GateDetail(BaseModel):
    data: dict[str, Any]


class GateResponseInput(BaseModel):
    response_type: str
    chosen_option: str = ""
    modifications: str = ""
    feedback: str = ""
    combine_instructions: str = ""
    revision_feedback: str = ""
    redirect_instructions: str = ""


# ---------------------------------------------------------------------------
# Artifact schemas
# ---------------------------------------------------------------------------

class ArtifactSummary(BaseModel):
    artifact_id: str
    file_path: str
    task_id: str = ""
    tier: int = 0
    subsystem: str = ""


class ArtifactDetail(BaseModel):
    data: dict[str, Any]
    lineage: list[str] = []


# ---------------------------------------------------------------------------
# Decision / Lineage schemas
# ---------------------------------------------------------------------------

class DecisionEntry(BaseModel):
    decision_id: str
    timestamp: str = ""
    decision_type: str = ""
    made_by: str = ""
    description: str = ""
    rationale: str = ""


class LineageEntry(BaseModel):
    artifact_id: str
    file_path: str
    lineage: list[str] = []
    produced_by: str = ""
    task_id: str = ""


# ---------------------------------------------------------------------------
# Cost schemas
# ---------------------------------------------------------------------------

class CostReportResponse(BaseModel):
    report_text: str
    total_cost: float = 0.0
    breakdown: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Export schemas
# ---------------------------------------------------------------------------

class ExportInfo(BaseModel):
    file_count: int
    total_size: int
    files: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Health / WebSocket
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    total_tasks: int = 0
    completed_tasks: int = 0
    rejected_tasks: int = 0
    pending_gates: int = 0
    total_cost: float = 0.0


class WSMessage(BaseModel):
    event: str
    project_id: str
    data: dict[str, Any] = {}
    timestamp: str = ""
