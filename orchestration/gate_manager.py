"""Gate Manager — human approval checkpoints.

Doc 08 §5: Controls approval checkpoints where the human reviews and decides.
When a gate activates, the orchestration engine stops all work on that project.
Nothing proceeds until the human responds.

Gates are stored as JSON in projects/{project_id}/gates/{gate_id}.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orchestration.models import (
    Gate,
    GateOption,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
)
from orchestration.project_state import ProjectState, generate_id
from orchestration.lineage import record_gate_decision


class GateManager:
    """Manages gate lifecycle: creation, storage, response handling."""

    def __init__(self, projects_dir: str | Path):
        self.projects_dir = Path(projects_dir)

    def _gates_dir(self, project_id: str) -> Path:
        d = self.projects_dir / project_id / "gates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_gate(
        self,
        project: ProjectState,
        gate_type: GateType,
        summary: str,
        architect_raw_response: str = "",
        options: list[GateOption] | None = None,
        questions: list[str] | None = None,
        recommended_option: str = "",
    ) -> Gate:
        """Create a new gate and save it.

        Sets the gate as pending on the project.
        """
        gate = Gate(
            gate_id=generate_id("gate"),
            gate_type=gate_type.value,
            phase=project.current_phase,
            trigger=f"Phase {project.current_phase} complete",
            status=GateStatus.PENDING.value,
            summary=summary,
            architect_raw_response=architect_raw_response,
            options=[o.to_dict() for o in (options or [])],
            questions=questions or [],
            recommended_option=recommended_option,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Save gate JSON
        self._save_gate(project.project_id, gate)

        # Update project state
        project.gates.append(gate)
        project.pending_gate = gate
        project.blocked_on = [f"Gate {gate.gate_id} ({gate.gate_type}) awaiting human response"]

        return gate

    # ------------------------------------------------------------------
    # Respond
    # ------------------------------------------------------------------

    def respond_to_gate(
        self,
        project: ProjectState,
        gate_id: str,
        response: GateResponse,
    ) -> Gate:
        """Record a human response to a gate.

        Returns the updated gate. Clears the project's pending gate and blocked status.
        """
        gate = self._find_gate(project, gate_id)
        if gate.status != GateStatus.PENDING.value:
            raise ValueError(f"Gate {gate_id} is not pending (status: {gate.status})")

        response.responded_at = datetime.now(timezone.utc).isoformat()

        # Update gate
        gate.human_response = response.to_dict()
        gate.approved_at = response.responded_at

        if response.response_type == GateResponseType.REJECT.value:
            gate.status = GateStatus.REJECTED.value
        else:
            gate.status = GateStatus.APPROVED.value
            if response.response_type == GateResponseType.CHOOSE_WITH_MODIFICATIONS.value:
                gate.conditions = [response.modifications]
            elif response.response_type == GateResponseType.REVISE_AND_PROCEED.value:
                gate.conditions = [response.revision_feedback]

        # Save updated gate
        self._save_gate(project.project_id, gate)

        # Tier 6: record human decision
        record_gate_decision(project, self.projects_dir, gate, response)

        # Clear project blocked state
        project.pending_gate = None
        project.blocked_on = []

        return gate

    def build_response_message(self, gate: Gate) -> str:
        """Build a message to feed back to the Architect session from a gate response.

        This translates the structured GateResponse into a natural language message
        the Architect can process.
        """
        if not gate.human_response:
            return ""

        resp = GateResponse.from_dict(gate.human_response)
        rt = resp.response_type

        if rt == GateResponseType.CHOOSE.value:
            return f"I choose Option {resp.chosen_option}. Proceed with this direction."

        elif rt == GateResponseType.CHOOSE_WITH_MODIFICATIONS.value:
            return (
                f"I choose Option {resp.chosen_option}, with these modifications:\n"
                f"{resp.modifications}\n\n"
                f"Apply these modifications and proceed — no new gate needed."
            )

        elif rt == GateResponseType.COMBINE.value:
            return (
                f"I want to combine elements from the options:\n"
                f"{resp.combine_instructions}\n\n"
                f"Synthesize this combination and proceed."
            )

        elif rt == GateResponseType.REVISE_AND_PROCEED.value:
            return (
                f"This is 80% right. Fix these things and continue without re-asking me:\n"
                f"{resp.revision_feedback}"
            )

        elif rt == GateResponseType.EXPLORE_DIFFERENTLY.value:
            return (
                f"None of these options work. I want options in a different direction:\n"
                f"{resp.redirect_instructions}\n\n"
                f"Generate new options based on this redirect."
            )

        elif rt == GateResponseType.REJECT.value:
            return (
                f"I'm rejecting this. Fundamental problem:\n"
                f"{resp.rejection_reason}\n\n"
                f"Return to the previous phase for rework."
            )

        return f"Human responded: {resp.response_type}"

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_pending_gate(self, project: ProjectState) -> Gate | None:
        """Return the current pending gate, if any."""
        return project.pending_gate

    def list_gates(self, project_id: str) -> list[Gate]:
        """Load all gates for a project from disk."""
        gates_dir = self._gates_dir(project_id)
        gates = []
        for path in sorted(gates_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            gates.append(Gate.from_dict(data))
        return gates

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_gate(self, project_id: str, gate: Gate) -> Path:
        gates_dir = self._gates_dir(project_id)
        path = gates_dir / f"{gate.gate_id}.json"
        path.write_text(gate.to_json(), encoding="utf-8")
        return path

    def _load_gate(self, project_id: str, gate_id: str) -> Gate:
        path = self._gates_dir(project_id) / f"{gate_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Gate {gate_id} not found at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return Gate.from_dict(data)

    @staticmethod
    def _find_gate(project: ProjectState, gate_id: str) -> Gate:
        for gate in project.gates:
            if gate.gate_id == gate_id:
                return gate
        raise ValueError(f"Gate {gate_id} not found in project {project.project_id}")
