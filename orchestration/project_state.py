"""Project State Store — persistent state for the entire project lifecycle.

Doc 08 §1: The orchestration engine's equivalent of the simulation's world_state.
Storage: JSON files on disk, one per project. Simple, inspectable, version-controllable.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from orchestration.models import (
    Artifact,
    BuilderTaskContract,
    Decision,
    Gate,
    GateStatus,
    Phase,
    ProjectHealth,
    ReviewResult,
    TaskStatus,
    VisionContract,
    _serialize,
)


def generate_id(prefix: str = "proj") -> str:
    """Generate a short, unique ID with prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ProjectState:
    """Full project state with JSON persistence.

    Follows Doc 08 §1 schema. Persists to projects/{project_id}/project_state.json.
    """

    def __init__(
        self,
        project_id: str = "",
        project_name: str = "",
        created_at: str = "",
        # Vision
        vision_contract: VisionContract | None = None,
        # Design
        architecture_template: str = "",
        subsystem_specs: dict[str, str] | None = None,
        # Build tracking
        current_tier: int = 0,
        current_phase: str = Phase.VISION_INTAKE.value,
        # Task management
        task_queue: list[dict] | None = None,
        active_tasks: dict[str, dict] | None = None,
        completed_tasks: list[dict] | None = None,
        # Gates
        gates: list[dict] | None = None,
        pending_gate: dict | None = None,
        # Artifacts
        artifacts: dict[str, dict] | None = None,
        # Lineage
        decision_log: list[dict] | None = None,
        review_log: list[dict] | None = None,
        # Status
        blocked_on: list[str] | None = None,
        health: dict | None = None,
        # Architect session
        architect_session_id: str = "",
    ):
        self.project_id = project_id or generate_id()
        self.project_name = project_name
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

        # Vision
        self.vision_contract = vision_contract or VisionContract()

        # Design (stored as raw markdown strings — filled by Architect in later tiers)
        self.architecture_template = architecture_template
        self.subsystem_specs = subsystem_specs or {}

        # Build tracking
        self.current_tier = current_tier
        self.current_phase = current_phase

        # Task management
        self.task_queue: list[BuilderTaskContract] = [
            BuilderTaskContract.from_dict(t) for t in (task_queue or [])
        ]
        self.active_tasks: dict[str, BuilderTaskContract] = {
            k: BuilderTaskContract.from_dict(v) for k, v in (active_tasks or {}).items()
        }
        self.completed_tasks: list[BuilderTaskContract] = [
            BuilderTaskContract.from_dict(t) for t in (completed_tasks or [])
        ]

        # Gates
        self.gates: list[Gate] = [Gate.from_dict(g) for g in (gates or [])]
        self.pending_gate: Gate | None = Gate.from_dict(pending_gate) if pending_gate else None

        # Artifacts
        self.artifacts: dict[str, Artifact] = {
            k: Artifact.from_dict(v) for k, v in (artifacts or {}).items()
        }

        # Lineage
        self.decision_log: list[Decision] = [
            Decision.from_dict(d) for d in (decision_log or [])
        ]
        self.review_log: list[ReviewResult] = [
            ReviewResult.from_dict(r) for r in (review_log or [])
        ]

        # Status
        self.blocked_on: list[str] = blocked_on or []
        self.health = ProjectHealth.from_dict(health) if health else ProjectHealth()

        # Architect session tracking
        self.architect_session_id = architect_session_id

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "created_at": self.created_at,
            "vision_contract": self.vision_contract.to_dict(),
            "architecture_template": self.architecture_template,
            "subsystem_specs": self.subsystem_specs,
            "current_tier": self.current_tier,
            "current_phase": self.current_phase,
            "task_queue": [t.to_dict() for t in self.task_queue],
            "active_tasks": {k: v.to_dict() for k, v in self.active_tasks.items()},
            "completed_tasks": [t.to_dict() for t in self.completed_tasks],
            "gates": [g.to_dict() for g in self.gates],
            "pending_gate": self.pending_gate.to_dict() if self.pending_gate else None,
            "artifacts": {k: v.to_dict() for k, v in self.artifacts.items()},
            "decision_log": [d.to_dict() for d in self.decision_log],
            "review_log": [r.to_dict() for r in self.review_log],
            "blocked_on": self.blocked_on,
            "health": self.health.to_dict(),
            "architect_session_id": self.architect_session_id,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectState":
        vc_data = data.get("vision_contract", {})
        vision = VisionContract.from_dict(vc_data) if vc_data else VisionContract()
        return cls(
            project_id=data.get("project_id", ""),
            project_name=data.get("project_name", ""),
            created_at=data.get("created_at", ""),
            vision_contract=vision,
            architecture_template=data.get("architecture_template", ""),
            subsystem_specs=data.get("subsystem_specs", {}),
            current_tier=data.get("current_tier", 0),
            current_phase=data.get("current_phase", Phase.VISION_INTAKE.value),
            task_queue=data.get("task_queue", []),
            active_tasks=data.get("active_tasks", {}),
            completed_tasks=data.get("completed_tasks", []),
            gates=data.get("gates", []),
            pending_gate=data.get("pending_gate"),
            artifacts=data.get("artifacts", {}),
            decision_log=data.get("decision_log", []),
            review_log=data.get("review_log", []),
            blocked_on=data.get("blocked_on", []),
            health=data.get("health"),
            architect_session_id=data.get("architect_session_id", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "ProjectState":
        return cls.from_dict(json.loads(text))

    # ------------------------------------------------------------------
    # Persistence — JSON files under projects/{project_id}/
    # ------------------------------------------------------------------

    def save(self, projects_dir: str | Path) -> Path:
        """Save project state to projects/{project_id}/project_state.json."""
        projects_dir = Path(projects_dir)
        project_dir = projects_dir / self.project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create standard subdirectories per Doc 08 file structure
        for subdir in [
            "subsystems", "tasks", "artifacts", "reviews",
            "gates", "lineage", "costs",
        ]:
            (project_dir / subdir).mkdir(exist_ok=True)

        # Save vision contract as markdown
        if self.vision_contract.raw_markdown:
            (project_dir / "vision_contract.md").write_text(
                self.vision_contract.raw_markdown, encoding="utf-8"
            )

        # Save architecture template if present
        if self.architecture_template:
            (project_dir / "architecture_template.md").write_text(
                self.architecture_template, encoding="utf-8"
            )

        # Save project state JSON
        state_path = project_dir / "project_state.json"
        state_path.write_text(self.to_json(), encoding="utf-8")

        return state_path

    @classmethod
    def load(cls, project_id: str, projects_dir: str | Path) -> "ProjectState":
        """Load project state from projects/{project_id}/project_state.json."""
        projects_dir = Path(projects_dir)
        state_path = projects_dir / project_id / "project_state.json"

        if not state_path.exists():
            raise FileNotFoundError(f"No project state found at {state_path}")

        text = state_path.read_text(encoding="utf-8")
        return cls.from_json(text)

    @staticmethod
    def list_projects(projects_dir: str | Path) -> list[str]:
        """List all project IDs in the projects directory."""
        projects_dir = Path(projects_dir)
        if not projects_dir.exists():
            return []
        return [
            d.name
            for d in sorted(projects_dir.iterdir())
            if d.is_dir() and (d / "project_state.json").exists()
        ]

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def status_summary(self) -> str:
        """Produce the PROJECT STATUS block per Doc 07 §Progress Tracking."""
        completed = [t.task_name for t in self.completed_tasks]
        in_progress = [t.task_name for t, _ in self.active_tasks.items()]
        pending_gates = [g for g in self.gates if g.status == GateStatus.PENDING.value]

        lines = [
            "PROJECT STATUS",
            "==============",
            f"Project:        {self.project_name} ({self.project_id})",
            f"Current Tier:   {self.current_tier} of 7",
            f"Active Phase:   {self.current_phase}",
            "",
            "Completed:",
        ]
        if completed:
            for name in completed:
                lines.append(f"  - {name}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("In Progress:")
        if in_progress:
            for name in in_progress:
                lines.append(f"  - {name}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("Blocked:")
        if self.blocked_on:
            for item in self.blocked_on:
                lines.append(f"  - {item}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("Pending Gates:")
        if pending_gates:
            for g in pending_gates:
                lines.append(f"  - [{g.gate_id}] {g.gate_type}: {g.summary}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append(f"Health: {self.health.completed_tasks}/{self.health.total_tasks} tasks complete")

        return "\n".join(lines)
