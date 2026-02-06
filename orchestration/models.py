"""Shared data models for Nexus Orchestrator.

All models serialize to/from JSON. Schemas follow Doc 07 (AI Architect Constitution)
and Doc 08 (Orchestration Engine Spec).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Phase(str, Enum):
    """Project lifecycle phase."""
    VISION_INTAKE = "vision_intake"
    SYSTEM_DESIGN = "system_design"
    DETAILED_DESIGN = "detailed_design"
    BUILD_DECOMPOSITION = "build_decomposition"
    BUILD_SUPERVISION = "build_supervision"
    VALIDATION = "validation"


class GateType(str, Enum):
    """Gate types from Doc 08 §5."""
    VISION_CONFIRMED = "vision_confirmed"
    SYSTEM_DESIGN = "system_design"
    DETAILED_DESIGN = "detailed_design"
    TIER_COMPLETE = "tier_complete"
    SCOPE_CHANGE = "scope_change"
    CONSTITUTIONAL_EXCEPTION = "constitutional"
    FINAL_DELIVERY = "final"


class GateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ReviewVerdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVISE = "revise"
    ESCALATE = "escalate"


class TaskType(str, Enum):
    """Builder task types — determines which constitutional docs are loaded.
    Maps to Context Budget table in Doc 07."""
    STATE_SCHEMA = "state_schema"
    FLOW = "flow"
    CONSTRAINT = "constraint"
    FAILURE_RECOVERY = "failure_recovery"
    DEPENDENCY_CASCADE = "dependency_cascade"
    UX_LAYER = "ux_layer"
    GENERAL = "general"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------

def _serialize(obj: Any) -> Any:
    """Convert dataclass trees to JSON-safe dicts."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return obj


class JSONSerializable:
    """Mixin for dataclasses that need JSON round-trip."""

    def to_dict(self) -> dict:
        return _serialize(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "JSONSerializable":
        """Override in subclasses that have nested model fields."""
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "JSONSerializable":
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Vision Contract — Doc 06
# ---------------------------------------------------------------------------

class VisionValidationError(Exception):
    """Raised when a Vision Contract fails strict validation.

    Attributes:
        missing_fields: List of required fields that were empty or absent.
        warnings: List of recommended-but-optional fields that were empty.
    """

    def __init__(self, missing_fields: list[str], warnings: list[str] | None = None):
        self.missing_fields = missing_fields
        self.warnings = warnings or []
        lines = ["Vision Contract validation failed. Missing required fields:"]
        for f in missing_fields:
            lines.append(f"  - {f}")
        if self.warnings:
            lines.append("Warnings (recommended but not required):")
            for w in self.warnings:
                lines.append(f"  - {w}")
        lines.append("Use --relaxed to accept freeform input without validation.")
        super().__init__("\n".join(lines))


# Required fields: the Architect cannot proceed without these.
# Maps field name -> human-readable description for error messages.
_REQUIRED_VISION_FIELDS: dict[str, str] = {
    "project_name": "Project name (# heading or ## Identity section)",
    "purpose": "Purpose — what is this project for? (## Identity)",
    "primary_questions": "Primary questions — what should someone learn? (## Primary Questions)",
    "scope_in": "Scope (in) — what's included? (## Scope > ### In)",
    "non_negotiables": "Non-negotiables — hard constraints the Architect cannot override (## Non-Negotiables)",
}

# Recommended fields: useful but the Architect can ask for them later.
_RECOMMENDED_VISION_FIELDS: dict[str, str] = {
    "domain": "Domain (## Identity)",
    "audience": "Audience — who is this for? (## Audience)",
    "key_systems": "Key systems — what subsystems to model (## Key Systems)",
    "feel": "Feel — reference experience, core tension, pacing (## Feel)",
}


@dataclass
class VisionContract(JSONSerializable):
    """Human's creative brief. Parsed from markdown."""
    project_name: str = ""
    domain: str = ""
    purpose: str = ""
    primary_questions: list[str] = field(default_factory=list)
    feel: dict[str, str] = field(default_factory=dict)
    scope_in: list[str] = field(default_factory=list)
    scope_out: list[str] = field(default_factory=list)
    scope_not_modeled: list[str] = field(default_factory=list)
    key_systems: list[str] = field(default_factory=list)
    non_negotiables: list[str] = field(default_factory=list)
    target_fidelity: int = 3
    time_model: dict[str, str] = field(default_factory=dict)
    audience: str = ""
    output_preferences: list[str] = field(default_factory=list)
    technology_constraints: list[str] = field(default_factory=list)
    inspirations: list[str] = field(default_factory=list)
    approval_gates: list[str] = field(default_factory=list)
    raw_markdown: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "VisionContract":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        """Validate required fields. Returns list of warnings for recommended fields.

        Raises:
            VisionValidationError: If any required fields are missing/empty.
        """
        missing: list[str] = []
        for field_name, description in _REQUIRED_VISION_FIELDS.items():
            value = getattr(self, field_name)
            if not value:  # catches "", [], {}, None
                missing.append(description)

        warnings: list[str] = []
        for field_name, description in _RECOMMENDED_VISION_FIELDS.items():
            value = getattr(self, field_name)
            if not value:
                warnings.append(description)

        if missing:
            raise VisionValidationError(missing, warnings)

        return warnings

    @classmethod
    def from_markdown(cls, text: str, *, strict: bool = True) -> "VisionContract":
        """Parse a Vision Contract markdown file into structured data.

        Args:
            text: Raw markdown content of the vision contract.
            strict: If True (default), validate required fields after parsing.
                    Set to False for freeform/incomplete vision documents.

        Raises:
            VisionValidationError: If strict=True and required fields are missing.
        """
        vc = cls(raw_markdown=text)
        current_section = ""
        current_subsection = ""
        buffer: list[str] = []

        def flush():
            nonlocal buffer
            content = "\n".join(buffer).strip()
            if not content:
                buffer = []
                return
            _apply_section(vc, current_section, current_subsection, content)
            buffer = []

        for line in text.splitlines():
            stripped = line.strip()

            # Detect headings
            if stripped.startswith("## "):
                flush()
                current_section = stripped.lstrip("# ").strip().lower()
                current_subsection = ""
            elif stripped.startswith("### "):
                flush()
                current_subsection = stripped.lstrip("# ").strip().lower()
            elif stripped.startswith("# ") and not current_section:
                # Top-level title — use as project name
                vc.project_name = stripped.lstrip("# ").strip()
            else:
                buffer.append(stripped)

        flush()

        if strict:
            vc.validate()

        return vc


def _apply_section(vc: VisionContract, section: str, subsection: str, content: str) -> None:
    """Map markdown sections to VisionContract fields."""
    lines = [l for l in content.splitlines() if l.strip()]
    bullets = [l.lstrip("-•* ").strip() for l in lines if l.startswith(("-", "•", "*"))]

    if "identity" in section:
        for line in lines:
            if "domain" in line.lower() and ":" in line:
                vc.domain = line.split(":", 1)[1].strip()
            elif "purpose" in line.lower() and ":" in line:
                vc.purpose = line.split(":", 1)[1].strip()
            elif not vc.project_name and line.strip():
                vc.project_name = line.strip()
        if not vc.purpose and not bullets:
            vc.purpose = content

    elif "primary question" in section or "question" in section:
        vc.primary_questions = bullets or [l for l in lines if l]

    elif "feel" in section:
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                vc.feel[k.strip().lower().lstrip("-•* ")] = v.strip()

    elif "scope" in section:
        if "not modeled" in subsection or "not_modeled" in subsection:
            vc.scope_not_modeled = bullets or lines
        elif "out" in subsection:
            vc.scope_out = bullets or lines
        elif "in" in subsection:
            vc.scope_in = bullets or lines
        else:
            # No subsection — try to parse from content
            vc.scope_in = bullets or lines

    elif "key system" in section or "systems" in section:
        vc.key_systems = bullets or lines

    elif "non-negotiable" in section or "non_negotiable" in section:
        vc.non_negotiables = bullets or lines

    elif "fidelity" in section or "target" in section:
        for line in lines:
            for word in line.split():
                if word.isdigit() and 1 <= int(word) <= 7:
                    vc.target_fidelity = int(word)
                    return

    elif "time" in section:
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                vc.time_model[k.strip().lower().lstrip("-•* ")] = v.strip()

    elif "audience" in section:
        vc.audience = content

    elif "output" in section or "preference" in section:
        vc.output_preferences = bullets or lines

    elif "technology" in section or "constraint" in section:
        vc.technology_constraints = bullets or lines

    elif "inspiration" in section or "reference" in section:
        vc.inspirations = bullets or lines

    elif "approval" in section or "gate" in section:
        vc.approval_gates = bullets or lines


# ---------------------------------------------------------------------------
# Builder Task Contract — Doc 07
# ---------------------------------------------------------------------------

@dataclass
class BuilderTaskContract(JSONSerializable):
    """Scoped task contract dispatched to a builder. Doc 07 §Builder Task Contract."""
    task_id: str = ""
    task_name: str = ""
    build_tier: int = 1
    subsystem: str = ""
    task_type: str = TaskType.GENERAL.value
    objective: str = ""
    inputs: list[str] = field(default_factory=list)
    scope_must_build: list[str] = field(default_factory=list)
    scope_must_not_touch: list[str] = field(default_factory=list)
    schema_to_implement: str = ""
    rules_to_implement: list[str] = field(default_factory=list)
    constraints_to_enforce: list[str] = field(default_factory=list)
    verbs_used: list[str] = field(default_factory=list)
    interfaces_receives: list[str] = field(default_factory=list)
    interfaces_produces: list[str] = field(default_factory=list)
    test_criteria: list[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING.value
    assigned_provider: str = ""
    created_at: str = ""
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "BuilderTaskContract":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Gate — Doc 08 §5
# ---------------------------------------------------------------------------

@dataclass
class Gate(JSONSerializable):
    """Approval checkpoint where the human reviews and decides."""
    gate_id: str = ""
    gate_type: str = GateType.VISION_CONFIRMED.value
    trigger: str = ""
    status: str = GateStatus.PENDING.value
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    decisions_made: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    human_response: str | None = None
    approved_at: str | None = None
    conditions: list[str] = field(default_factory=list)
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Gate":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Review Result — Doc 08 §4
# ---------------------------------------------------------------------------

@dataclass
class CheckResult(JSONSerializable):
    """Single automated check result."""
    check_name: str = ""
    passed: bool = True
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CheckResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ReviewResult(JSONSerializable):
    """Result of reviewing builder output. Doc 08 §4."""
    review_id: str = ""
    task_id: str = ""
    verdict: str = ReviewVerdict.ACCEPT.value
    automated_checks: list[dict] = field(default_factory=list)
    architect_notes: str = ""
    integration_issues: list[str] = field(default_factory=list)
    revision_instructions: str | None = None
    escalation_reason: str | None = None
    reviewed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Decision & Artifact (Lineage) — Doc 08 §6
# ---------------------------------------------------------------------------

@dataclass
class Decision(JSONSerializable):
    """Design decision record for lineage tracking."""
    decision_id: str = ""
    timestamp: str = ""
    made_by: str = ""  # "human" | "architect" | "builder"
    decision_type: str = ""
    description: str = ""
    rationale: str = ""
    vision_reference: str | None = None
    constitutional_basis: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Artifact(JSONSerializable):
    """Produced artifact with lineage chain."""
    artifact_id: str = ""
    file_path: str = ""
    produced_by: str = ""
    task_id: str | None = None
    tier: int = 1
    subsystem: str | None = None
    review_id: str = ""
    lineage: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Builder Output — Doc 07 §Builder Output Manifest
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage(JSONSerializable):
    """Token usage for a builder session."""
    input: int = 0
    output: int = 0
    provider: str = ""
    model: str = ""
    estimated_cost: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "TokenUsage":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BuilderArtifact(JSONSerializable):
    """Single artifact entry in a builder output manifest."""
    file: str = ""
    implements: str = ""
    task_contract_section: str = ""
    verbs_used: list[str] = field(default_factory=list)
    constraints_enforced: list[str] = field(default_factory=list)
    coverage: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "BuilderArtifact":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class IncompleteItem(JSONSerializable):
    """Item not completed by builder."""
    item: str = ""
    reason: str = ""
    blocked_by: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "IncompleteItem":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BuilderOutputManifest(JSONSerializable):
    """Builder output manifest per Doc 07 spec."""
    task_id: str = ""
    builder_session_id: str = ""
    completed_at: str = ""
    artifacts: list[dict] = field(default_factory=list)
    incomplete: list[dict] = field(default_factory=list)
    questions_for_architect: list[str] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "BuilderOutputManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Project Health — summary metrics
# ---------------------------------------------------------------------------

@dataclass
class ProjectHealth(JSONSerializable):
    """Summary health metrics for a project."""
    total_tasks: int = 0
    completed_tasks: int = 0
    rejected_tasks: int = 0
    pending_gates: int = 0
    total_cost: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectHealth":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
