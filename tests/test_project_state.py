"""Tests for ProjectState model and JSON persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from orchestration.models import (
    Artifact,
    BuilderTaskContract,
    Decision,
    Gate,
    GateStatus,
    GateType,
    Phase,
    ProjectHealth,
    ReviewResult,
    ReviewVerdict,
    TaskStatus,
    TaskType,
    VisionContract,
    VisionValidationError,
)
from orchestration.project_state import ProjectState, generate_id


# ---------------------------------------------------------------------------
# VisionContract
# ---------------------------------------------------------------------------

SAMPLE_VISION_MD = """\
# Data Center Ops Sim

## Identity
- Domain: Data center operations
- Purpose: Train NOC operators in incident response

## Primary Questions
- How do cascading failures propagate through cooling and power?
- What staffing levels prevent SLA breaches during peak load?
- When should operators escalate vs. handle locally?

## Feel
- Reference experience: Flight simulator training
- Core tension: Resource scarcity under time pressure
- Pacing: Slow burn punctuated by crises

## Scope
### In
- Power distribution
- Cooling systems
- Staffing and shifts
### Out
- Physical security
- Network topology detail
### Not modeled
- Financial accounting

## Key Systems
- Power
- Cooling
- Staffing
- Incident Response

## Non-Negotiables
- Deterministic replay
- All actions from verb catalog
- Constraint violations must reject, not warn

## Target Fidelity
Tier 5

## Time Model
- Tick size: 5 minutes
- Run horizon: 24 hours

## Audience
NOC operator training

## Output Preferences
- Dashboard
- Timeline
- Decision cards

## Technology Constraints
- Python 3.11+

## Inspirations
- Factorio
- Oxygen Not Included

## Approval Gates
- System design review
- Tier completion review
"""


class TestVisionContractParsing:
    def test_from_markdown_parses_name(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert vc.project_name == "Data Center Ops Sim"

    def test_from_markdown_parses_domain(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert "data center" in vc.domain.lower()

    def test_from_markdown_parses_purpose(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert "NOC" in vc.purpose or "train" in vc.purpose.lower()

    def test_from_markdown_parses_questions(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert len(vc.primary_questions) == 3
        assert any("cascading" in q for q in vc.primary_questions)

    def test_from_markdown_parses_feel(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert "reference experience" in vc.feel or "flight" in str(vc.feel).lower()

    def test_from_markdown_parses_scope(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert len(vc.scope_in) >= 2
        assert len(vc.scope_out) >= 1

    def test_from_markdown_parses_key_systems(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert len(vc.key_systems) >= 3

    def test_from_markdown_parses_non_negotiables(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert len(vc.non_negotiables) >= 2

    def test_from_markdown_parses_fidelity(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert vc.target_fidelity == 5

    def test_from_markdown_parses_audience(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert "NOC" in vc.audience

    def test_from_markdown_preserves_raw(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        assert vc.raw_markdown == SAMPLE_VISION_MD

    def test_round_trip_json(self):
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        j = vc.to_json()
        vc2 = VisionContract.from_json(j)
        assert vc2.project_name == vc.project_name
        assert vc2.primary_questions == vc.primary_questions
        assert vc2.target_fidelity == vc.target_fidelity


# ---------------------------------------------------------------------------
# ProjectState persistence
# ---------------------------------------------------------------------------

class TestProjectStatePersistence:
    def _make_project(self) -> ProjectState:
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD)
        project = ProjectState(
            project_name="Test Project",
            vision_contract=vc,
            current_tier=1,
            current_phase=Phase.SYSTEM_DESIGN.value,
        )
        project.gates.append(Gate(
            gate_id="gate_001",
            gate_type=GateType.VISION_CONFIRMED.value,
            status=GateStatus.APPROVED.value,
            summary="Vision confirmed by human.",
        ))
        project.task_queue.append(BuilderTaskContract(
            task_id="task_001",
            task_name="Implement power state schema",
            build_tier=1,
            subsystem="power",
            task_type=TaskType.STATE_SCHEMA.value,
            objective="Create power subsystem state model",
        ))
        project.decision_log.append(Decision(
            decision_id="dec_001",
            made_by="architect",
            decision_type="architecture",
            description="Separate power and cooling into distinct subsystems",
            rationale="Better isolation for independent builder tasks",
        ))
        return project

    def test_save_and_load_roundtrip(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            project.save(tmpdir)
            loaded = ProjectState.load(project.project_id, tmpdir)

            assert loaded.project_id == project.project_id
            assert loaded.project_name == project.project_name
            assert loaded.current_tier == 1
            assert loaded.current_phase == Phase.SYSTEM_DESIGN.value
            assert loaded.vision_contract.project_name == "Data Center Ops Sim"

    def test_save_creates_directory_structure(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            project.save(tmpdir)
            project_dir = Path(tmpdir) / project.project_id

            assert (project_dir / "project_state.json").exists()
            assert (project_dir / "vision_contract.md").exists()
            assert (project_dir / "subsystems").is_dir()
            assert (project_dir / "tasks").is_dir()
            assert (project_dir / "artifacts").is_dir()
            assert (project_dir / "reviews").is_dir()
            assert (project_dir / "gates").is_dir()
            assert (project_dir / "lineage").is_dir()
            assert (project_dir / "costs").is_dir()

    def test_save_creates_valid_json(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = project.save(tmpdir)
            data = json.loads(state_path.read_text())

            assert data["project_id"] == project.project_id
            assert data["current_tier"] == 1
            assert len(data["gates"]) == 1
            assert len(data["task_queue"]) == 1
            assert len(data["decision_log"]) == 1

    def test_gates_persist_correctly(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            project.save(tmpdir)
            loaded = ProjectState.load(project.project_id, tmpdir)

            assert len(loaded.gates) == 1
            assert loaded.gates[0].gate_id == "gate_001"
            assert loaded.gates[0].status == GateStatus.APPROVED.value

    def test_tasks_persist_correctly(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            project.save(tmpdir)
            loaded = ProjectState.load(project.project_id, tmpdir)

            assert len(loaded.task_queue) == 1
            assert loaded.task_queue[0].task_id == "task_001"
            assert loaded.task_queue[0].subsystem == "power"

    def test_decisions_persist_correctly(self):
        project = self._make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            project.save(tmpdir)
            loaded = ProjectState.load(project.project_id, tmpdir)

            assert len(loaded.decision_log) == 1
            assert loaded.decision_log[0].decision_id == "dec_001"
            assert loaded.decision_log[0].made_by == "architect"

    def test_list_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = ProjectState(project_name="Alpha")
            p2 = ProjectState(project_name="Beta")
            p1.save(tmpdir)
            p2.save(tmpdir)

            ids = ProjectState.list_projects(tmpdir)
            assert len(ids) == 2
            assert p1.project_id in ids
            assert p2.project_id in ids

    def test_load_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                ProjectState.load("nonexistent", tmpdir)

    def test_status_summary_format(self):
        project = self._make_project()
        summary = project.status_summary()
        assert "PROJECT STATUS" in summary
        assert project.project_name in summary
        assert "Tier" in summary


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------

class TestModelSerialization:
    def test_builder_task_contract_roundtrip(self):
        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Test task",
            build_tier=2,
            subsystem="cooling",
            verbs_used=["allocate_resource", "throttle_flow"],
        )
        j = task.to_json()
        task2 = BuilderTaskContract.from_json(j)
        assert task2.task_id == "task_001"
        assert task2.verbs_used == ["allocate_resource", "throttle_flow"]

    def test_gate_roundtrip(self):
        gate = Gate(
            gate_id="gate_001",
            gate_type=GateType.SYSTEM_DESIGN.value,
            summary="System design review",
            options=[{"name": "Option A"}, {"name": "Option B"}],
        )
        j = gate.to_json()
        gate2 = Gate.from_json(j)
        assert gate2.gate_id == "gate_001"
        assert len(gate2.options) == 2

    def test_review_result_roundtrip(self):
        review = ReviewResult(
            review_id="rev_001",
            task_id="task_001",
            verdict=ReviewVerdict.REJECT.value,
            architect_notes="Missing constraint enforcement",
            revision_instructions="Add hard rejection for capacity violations",
        )
        j = review.to_json()
        review2 = ReviewResult.from_json(j)
        assert review2.verdict == "reject"
        assert review2.revision_instructions is not None

    def test_decision_roundtrip(self):
        dec = Decision(
            decision_id="dec_001",
            made_by="architect",
            decision_type="architecture",
            description="Use separate subsystems",
            constitutional_basis="Doc 01 §Nested Systems",
        )
        j = dec.to_json()
        dec2 = Decision.from_json(j)
        assert dec2.constitutional_basis == "Doc 01 §Nested Systems"

    def test_artifact_roundtrip(self):
        art = Artifact(
            artifact_id="art_001",
            file_path="src/subsystems/cooling.py",
            produced_by="task_003",
            lineage=["vision_q1", "dec_005", "task_003", "art_001"],
        )
        j = art.to_json()
        art2 = Artifact.from_json(j)
        assert len(art2.lineage) == 4

    def test_generate_id_format(self):
        pid = generate_id("proj")
        assert pid.startswith("proj_")
        assert len(pid) == 17  # "proj_" + 12 hex chars

        tid = generate_id("task")
        assert tid.startswith("task_")


# ---------------------------------------------------------------------------
# Strict mode validation
# ---------------------------------------------------------------------------

MINIMAL_INVALID_MD = """\
# Just A Title

Some text without any structured sections.
"""

MISSING_QUESTIONS_MD = """\
# My Sim

## Identity
- Domain: Testing
- Purpose: Test the validator

## Scope
### In
- Everything

## Non-Negotiables
- Deterministic
"""


class TestVisionContractStrictMode:
    def test_complete_vision_passes_strict(self):
        """SAMPLE_VISION_MD has all required fields — should pass."""
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD, strict=True)
        assert vc.project_name == "Data Center Ops Sim"

    def test_minimal_markdown_fails_strict(self):
        """Markdown with only a title should fail strict validation."""
        with pytest.raises(VisionValidationError) as exc_info:
            VisionContract.from_markdown(MINIMAL_INVALID_MD, strict=True)
        err = exc_info.value
        assert len(err.missing_fields) >= 3
        assert "purpose" in str(err).lower()

    def test_minimal_markdown_passes_relaxed(self):
        """Same markdown should work fine with strict=False."""
        vc = VisionContract.from_markdown(MINIMAL_INVALID_MD, strict=False)
        assert vc.project_name == "Just A Title"

    def test_missing_questions_fails_strict(self):
        """Missing primary_questions should be caught."""
        with pytest.raises(VisionValidationError) as exc_info:
            VisionContract.from_markdown(MISSING_QUESTIONS_MD, strict=True)
        err = exc_info.value
        assert any("question" in f.lower() for f in err.missing_fields)

    def test_error_message_lists_all_missing(self):
        """Error message should list each missing required field."""
        with pytest.raises(VisionValidationError) as exc_info:
            VisionContract.from_markdown(MINIMAL_INVALID_MD, strict=True)
        msg = str(exc_info.value)
        assert "Missing required fields" in msg
        assert "--relaxed" in msg

    def test_error_includes_clear_descriptions(self):
        """Each missing field should have a human-readable description."""
        with pytest.raises(VisionValidationError) as exc_info:
            VisionContract.from_markdown(MINIMAL_INVALID_MD, strict=True)
        msg = str(exc_info.value)
        # Should mention section locations
        assert "## " in msg or "(#" in msg

    def test_warnings_for_recommended_fields(self):
        """Strict mode should return warnings for missing recommended fields."""
        vc = VisionContract.from_markdown(SAMPLE_VISION_MD, strict=True)
        # SAMPLE_VISION_MD has most fields, but validate() returns warnings list
        warnings = vc.validate()
        # Warnings are a list (may be empty if all recommended fields present)
        assert isinstance(warnings, list)

    def test_validate_on_constructed_object(self):
        """validate() can be called independently of from_markdown()."""
        vc = VisionContract(project_name="Test", purpose="Testing")
        with pytest.raises(VisionValidationError) as exc_info:
            vc.validate()
        assert len(exc_info.value.missing_fields) > 0

    def test_default_is_strict(self):
        """from_markdown() is strict by default (no explicit parameter needed)."""
        with pytest.raises(VisionValidationError):
            VisionContract.from_markdown(MINIMAL_INVALID_MD)
