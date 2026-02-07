"""Lineage and Observability — decision tracking, artifact lineage, usage recording.

Tier 6: Every design decision is tracked with rationale and constitutional basis.
Every artifact traces back to the vision. Usage data collected per AI call.

All persistence uses append-only JSONL (one JSON object per line).
File layout:
    projects/{project_id}/lineage/decisions.jsonl
    projects/{project_id}/lineage/artifacts.jsonl
    projects/{project_id}/costs/usage.jsonl
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orchestration.models import (
    Artifact,
    Decision,
    GateResponse,
    GateResponseType,
    ProjectHealth,
    TaskStatus,
)
from orchestration.project_state import ProjectState, generate_id


# ---------------------------------------------------------------------------
# JSONL directory helpers
# ---------------------------------------------------------------------------

def _lineage_dir(project_id: str, projects_dir: str | Path) -> Path:
    """Return the lineage/ directory for a project, creating it if needed."""
    d = Path(projects_dir) / project_id / "lineage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _costs_dir(project_id: str, projects_dir: str | Path) -> Path:
    """Return the costs/ directory for a project, creating it if needed."""
    d = Path(projects_dir) / project_id / "costs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# JSONL append / load (pure I/O)
# ---------------------------------------------------------------------------

def append_decision(decision: Decision, project_id: str, projects_dir: str | Path) -> None:
    """Append one Decision as a JSON line to lineage/decisions.jsonl."""
    path = _lineage_dir(project_id, projects_dir) / "decisions.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision.to_dict()) + "\n")


def append_artifact_lineage(artifact: Artifact, project_id: str, projects_dir: str | Path) -> None:
    """Append one Artifact (with lineage chain) to lineage/artifacts.jsonl."""
    path = _lineage_dir(project_id, projects_dir) / "artifacts.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(artifact.to_dict()) + "\n")


def append_usage(usage_entry: dict, project_id: str, projects_dir: str | Path) -> None:
    """Append one usage entry to costs/usage.jsonl.

    usage_entry schema:
        {timestamp, task_id, role, provider, model, input_tokens, output_tokens,
         estimated_cost, phase, tier}
    """
    path = _costs_dir(project_id, projects_dir) / "usage.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(usage_entry) + "\n")


def load_decisions(project_id: str, projects_dir: str | Path) -> list[Decision]:
    """Load all decisions from lineage/decisions.jsonl."""
    path = _lineage_dir(project_id, projects_dir) / "decisions.jsonl"
    if not path.exists():
        return []
    decisions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            decisions.append(Decision.from_dict(json.loads(line)))
    return decisions


def load_artifact_lineage(project_id: str, projects_dir: str | Path) -> list[Artifact]:
    """Load all artifacts with lineage from lineage/artifacts.jsonl."""
    path = _lineage_dir(project_id, projects_dir) / "artifacts.jsonl"
    if not path.exists():
        return []
    artifacts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            artifacts.append(Artifact.from_dict(json.loads(line)))
    return artifacts


def load_usage(project_id: str, projects_dir: str | Path) -> list[dict]:
    """Load all usage entries from costs/usage.jsonl."""
    path = _costs_dir(project_id, projects_dir) / "usage.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Decision recording
# ---------------------------------------------------------------------------

def record_phase_decision(
    project: ProjectState,
    projects_dir: str | Path,
    decision_type: str,
    description: str,
    rationale: str = "",
    made_by: str = "architect",
    vision_reference: str | None = None,
    constitutional_basis: str = "",
) -> Decision:
    """Create a Decision with generated ID + timestamp, append to JSONL and project.decision_log."""
    decision = Decision(
        decision_id=generate_id("dec"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        made_by=made_by,
        decision_type=decision_type,
        description=description,
        rationale=rationale,
        vision_reference=vision_reference,
        constitutional_basis=constitutional_basis,
    )
    append_decision(decision, project.project_id, projects_dir)
    project.decision_log.append(decision)
    return decision


def record_gate_decision(
    project: ProjectState,
    projects_dir: str | Path,
    gate,
    response: GateResponse,
) -> Decision:
    """Extract decision info from a gate response and record it.

    Made_by is always "human" since gates are human approval checkpoints.
    """
    # Build description from gate summary + response details
    resp_type = response.response_type
    detail = ""
    if resp_type == GateResponseType.CHOOSE.value:
        detail = f"Chose option {response.chosen_option}"
    elif resp_type == GateResponseType.CHOOSE_WITH_MODIFICATIONS.value:
        detail = f"Chose option {response.chosen_option} with modifications: {response.modifications}"
    elif resp_type == GateResponseType.COMBINE.value:
        detail = f"Combined options: {response.combine_instructions}"
    elif resp_type == GateResponseType.REVISE_AND_PROCEED.value:
        detail = f"Revise and proceed: {response.revision_feedback}"
    elif resp_type == GateResponseType.EXPLORE_DIFFERENTLY.value:
        detail = f"Explore differently: {response.redirect_instructions}"
    elif resp_type == GateResponseType.REJECT.value:
        detail = f"Rejected: {response.rejection_reason}"

    description = f"Gate {gate.gate_id} ({gate.gate_type}): {detail}"

    decision = Decision(
        decision_id=generate_id("dec"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        made_by="human",
        decision_type=gate.gate_type,
        description=description,
        rationale=detail,
        vision_reference=None,
        constitutional_basis="",
    )
    append_decision(decision, project.project_id, projects_dir)
    project.decision_log.append(decision)
    return decision


# ---------------------------------------------------------------------------
# Artifact lineage
# ---------------------------------------------------------------------------

def build_artifact_lineage_chain(artifact: Artifact, project: ProjectState) -> list[str]:
    """Trace artifact → task → matching decisions → vision reference.

    Returns chain as list of IDs (best-effort — shorter chain if no matches).
    """
    chain: list[str] = []

    # Vision reference (always the project itself)
    chain.append(f"vision:{project.project_id}")

    # Find matching decisions (by subsystem/phase heuristics)
    for decision in project.decision_log:
        # Match by task_id mention or subsystem mention
        if artifact.task_id and artifact.task_id in decision.description:
            chain.append(decision.decision_id)
        elif artifact.subsystem and artifact.subsystem.lower() in decision.description.lower():
            chain.append(decision.decision_id)

    # Task reference
    if artifact.task_id:
        chain.append(f"task:{artifact.task_id}")

    # The artifact itself
    chain.append(artifact.artifact_id)

    return chain


def register_artifact_with_lineage(
    artifact: Artifact,
    project: ProjectState,
    projects_dir: str | Path,
) -> Artifact:
    """Build lineage chain, set artifact.lineage, append to JSONL, add to project.artifacts."""
    chain = build_artifact_lineage_chain(artifact, project)
    artifact.lineage = chain
    append_artifact_lineage(artifact, project.project_id, projects_dir)
    project.artifacts[artifact.file_path] = artifact
    return artifact


# ---------------------------------------------------------------------------
# Project health
# ---------------------------------------------------------------------------

def update_project_health(project: ProjectState) -> ProjectHealth:
    """Recalculate project health from current state."""
    total_tasks = len(project.task_queue) + len(project.completed_tasks)
    completed_tasks = len(project.completed_tasks)
    rejected_tasks = sum(
        1 for t in project.completed_tasks
        if t.status == TaskStatus.REJECTED.value
    )
    pending_gates = sum(
        1 for g in project.gates if g.status == "pending"
    )

    # Calculate total cost from build results or usage data
    total_cost = 0.0
    for t in project.completed_tasks:
        if hasattr(t, "completed_at") and t.completed_at:
            # Check for cost in build result manifests (if available)
            pass

    # Try to get cost from usage JSONL if we have project info
    # (health is updated in-memory, cost tracking is separate)

    health = ProjectHealth(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        rejected_tasks=rejected_tasks,
        pending_gates=pending_gates,
        total_cost=total_cost,
    )
    project.health = health
    return health
