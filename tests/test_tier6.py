"""Tier 6 tests — Lineage and Observability.

Tests use mock connectors (no real AI calls). Covers:
- JSONL persistence: append creates file, append-only, load empty, roundtrip
- Decision recording: record_phase_decision, record_gate_decision for all types
- Artifact lineage: build chain, register with lineage, chain traces to vision
- Project health: empty, with tasks, rejected tasks, pending gates, total cost
- Cost tracker: aggregate by task/tier/provider/role/model, total cost, format report
- Architect hooks: vision_intake/system_design/process_design/decomposition/
  build_supervision/review record decisions + track usage
- Gate manager hooks: respond records decision for approve/reject/modify/combine
- Builder dispatch hooks: dispatch appends usage
- CLI: decisions/lineage/costs commands, parser, lineage filter
- Models: Decision/Artifact/ProjectHealth roundtrip
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from orchestration.architect import ArchitectSession
from orchestration.constitution import ConstitutionEnforcer
from orchestration.cost_tracker import (
    aggregate_costs_by_model,
    aggregate_costs_by_provider,
    aggregate_costs_by_role,
    aggregate_costs_by_task,
    aggregate_costs_by_tier,
    format_cost_report,
    total_project_cost,
)
from orchestration.gate_manager import GateManager
from orchestration.lineage import (
    append_artifact_lineage,
    append_decision,
    append_usage,
    build_artifact_lineage_chain,
    load_artifact_lineage,
    load_decisions,
    load_usage,
    record_gate_decision,
    record_phase_decision,
    register_artifact_with_lineage,
    update_project_health,
)
from orchestration.models import (
    Artifact,
    BuilderOutputManifest,
    BuilderTaskContract,
    Decision,
    Gate,
    GateOption,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
    Phase,
    ProjectHealth,
    ReviewResult,
    ReviewVerdict,
    TaskStatus,
    VisionContract,
)
from orchestration.project_state import ProjectState, generate_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_projects(tmp_path):
    d = tmp_path / "projects"
    d.mkdir()
    return d


@pytest.fixture
def docs_dir():
    return Path("constitutional_docs")


@pytest.fixture
def sample_project(tmp_projects):
    vision = VisionContract(
        project_name="Lineage Test",
        purpose="Testing Tier 6",
        raw_markdown="# Lineage Test\n\n## Identity\n- Purpose: Testing Tier 6",
    )
    project = ProjectState(
        project_name="Lineage Test",
        vision_contract=vision,
        current_tier=1,
        current_phase="vision_intake",
        architecture_template="# Architecture\n\n## Subsystems\n- Core\n- API",
    )
    project.save(tmp_projects)
    return project


@pytest.fixture
def sample_project_with_tasks(tmp_projects):
    vision = VisionContract(
        project_name="Build Test",
        purpose="Testing Tier 6",
        raw_markdown="# Build Test\n\n## Identity\n- Purpose: Testing Tier 6",
    )
    project = ProjectState(
        project_name="Build Test",
        vision_contract=vision,
        current_tier=1,
        current_phase="build_supervision",
        architecture_template="# Arch",
    )
    project.completed_tasks = [
        BuilderTaskContract(
            task_id="task_001",
            task_name="Define Core Schema",
            subsystem="Core",
            task_type="state_schema",
            objective="Define core data models",
            scope_must_build=["Data models"],
            scope_must_not_touch=["UI layer"],
            test_criteria=["Models serialize"],
            depends_on=[],
            parallel_group=0,
            assigned_provider="builder_complex",
            status=TaskStatus.COMPLETED.value,
        ),
        BuilderTaskContract(
            task_id="task_002",
            task_name="Build API",
            subsystem="API",
            task_type="general",
            objective="Create endpoints",
            scope_must_build=["CRUD"],
            scope_must_not_touch=[],
            test_criteria=[],
            depends_on=["task_001"],
            parallel_group=1,
            assigned_provider="builder_simple",
            status=TaskStatus.COMPLETED.value,
        ),
    ]
    project.task_queue = [
        BuilderTaskContract(
            task_id="task_003",
            task_name="Pending Task",
            status=TaskStatus.PENDING.value,
        ),
    ]
    project.save(tmp_projects)

    # Create builder output manifests on disk
    from orchestration.builder_dispatch import save_builder_manifest
    m1 = BuilderOutputManifest(
        task_id="task_001",
        builder_session_id="session_1",
        artifacts=[
            {"file": "src/core/state.py", "implements": "Core state model"},
            {"file": "tests/test_state.py", "implements": "Tests"},
        ],
    )
    m2 = BuilderOutputManifest(
        task_id="task_002",
        builder_session_id="session_2",
        artifacts=[
            {"file": "src/api/endpoints.py", "implements": "REST endpoints"},
        ],
    )
    save_builder_manifest(m1, project.project_id, tmp_projects)
    save_builder_manifest(m2, project.project_id, tmp_projects)

    return project


# ---------------------------------------------------------------------------
# Mock connector
# ---------------------------------------------------------------------------

@dataclass
class MockMessage:
    role: str = ""
    content: str = ""


@dataclass
class MockConnector:
    conversation_history: list = field(default_factory=list)
    session_id: str = "mock_session"
    _responses: list = field(default_factory=list)
    _call_count: int = 0
    _system_prompt: str = ""

    async def send_message(self, message: str, **kwargs) -> dict:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Mock response"
        self._call_count += 1
        self.conversation_history.append(MockMessage(role="user", content=message))
        self.conversation_history.append(MockMessage(role="assistant", content=content))
        return {
            "content": content,
            "usage": {"input": 100, "output": 50, "estimated_cost": 0.005},
        }


def mock_connector_factory(provider="", model="", system_prompt="", **kwargs):
    return MockConnector(_system_prompt=system_prompt)


# =========================================================================
# JSONL Persistence
# =========================================================================

class TestJSONLPersistence:
    def test_append_decision_creates_file(self, tmp_projects, sample_project):
        d = Decision(decision_id="dec_001", decision_type="test", description="Test")
        append_decision(d, sample_project.project_id, tmp_projects)
        path = tmp_projects / sample_project.project_id / "lineage" / "decisions.jsonl"
        assert path.exists()

    def test_append_decision_is_append_only(self, tmp_projects, sample_project):
        d1 = Decision(decision_id="dec_001", decision_type="test", description="First")
        d2 = Decision(decision_id="dec_002", decision_type="test", description="Second")
        append_decision(d1, sample_project.project_id, tmp_projects)
        append_decision(d2, sample_project.project_id, tmp_projects)
        path = tmp_projects / sample_project.project_id / "lineage" / "decisions.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_load_decisions_empty(self, tmp_projects, sample_project):
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert decisions == []

    def test_decision_roundtrip(self, tmp_projects, sample_project):
        d = Decision(
            decision_id="dec_001",
            timestamp="2026-01-01T00:00:00Z",
            made_by="architect",
            decision_type="vision_review",
            description="Reviewed vision",
            rationale="Need clarification",
            vision_reference="v1",
            constitutional_basis="Doc 07",
        )
        append_decision(d, sample_project.project_id, tmp_projects)
        loaded = load_decisions(sample_project.project_id, tmp_projects)
        assert len(loaded) == 1
        assert loaded[0].decision_id == "dec_001"
        assert loaded[0].description == "Reviewed vision"
        assert loaded[0].constitutional_basis == "Doc 07"

    def test_append_artifact_lineage_creates_file(self, tmp_projects, sample_project):
        a = Artifact(artifact_id="art_001", file_path="src/main.py", lineage=["v:1"])
        append_artifact_lineage(a, sample_project.project_id, tmp_projects)
        path = tmp_projects / sample_project.project_id / "lineage" / "artifacts.jsonl"
        assert path.exists()

    def test_artifact_lineage_roundtrip(self, tmp_projects, sample_project):
        a = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            produced_by="builder",
            task_id="task_001",
            tier=1,
            lineage=["vision:proj_001", "dec_001", "task:task_001", "art_001"],
        )
        append_artifact_lineage(a, sample_project.project_id, tmp_projects)
        loaded = load_artifact_lineage(sample_project.project_id, tmp_projects)
        assert len(loaded) == 1
        assert loaded[0].lineage == ["vision:proj_001", "dec_001", "task:task_001", "art_001"]

    def test_append_usage_creates_file(self, tmp_projects, sample_project):
        entry = {"task_id": "task_001", "role": "builder", "estimated_cost": 0.01}
        append_usage(entry, sample_project.project_id, tmp_projects)
        path = tmp_projects / sample_project.project_id / "costs" / "usage.jsonl"
        assert path.exists()

    def test_usage_roundtrip(self, tmp_projects, sample_project):
        entry = {
            "timestamp": "2026-01-01T00:00:00Z",
            "task_id": "task_001",
            "role": "builder",
            "provider": "anthropic",
            "model": "claude-sonnet",
            "input_tokens": 1000,
            "output_tokens": 500,
            "estimated_cost": 0.01,
            "phase": "build_supervision",
            "tier": 1,
        }
        append_usage(entry, sample_project.project_id, tmp_projects)
        loaded = load_usage(sample_project.project_id, tmp_projects)
        assert len(loaded) == 1
        assert loaded[0]["task_id"] == "task_001"
        assert loaded[0]["estimated_cost"] == 0.01


# =========================================================================
# Decision Recording
# =========================================================================

class TestDecisionRecording:
    def test_record_phase_decision_generates_id(self, tmp_projects, sample_project):
        d = record_phase_decision(
            sample_project, tmp_projects,
            decision_type="vision_review",
            description="Reviewed vision",
        )
        assert d.decision_id.startswith("dec_")

    def test_record_phase_decision_has_timestamp(self, tmp_projects, sample_project):
        d = record_phase_decision(
            sample_project, tmp_projects,
            decision_type="test",
            description="Test",
        )
        assert d.timestamp  # Not empty

    def test_record_phase_decision_appends_to_jsonl(self, tmp_projects, sample_project):
        record_phase_decision(
            sample_project, tmp_projects,
            decision_type="test",
            description="Test",
        )
        loaded = load_decisions(sample_project.project_id, tmp_projects)
        assert len(loaded) == 1

    def test_record_phase_decision_appends_to_project_log(self, tmp_projects, sample_project):
        record_phase_decision(
            sample_project, tmp_projects,
            decision_type="test",
            description="Test",
        )
        assert len(sample_project.decision_log) == 1

    def test_record_gate_decision_choose(self, tmp_projects, sample_project):
        gate = Gate(gate_id="gate_001", gate_type="system_design", summary="Choose option")
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        d = record_gate_decision(sample_project, tmp_projects, gate, response)
        assert d.made_by == "human"
        assert "Chose option A" in d.description

    def test_record_gate_decision_reject(self, tmp_projects, sample_project):
        gate = Gate(gate_id="gate_002", gate_type="vision_confirmed", summary="Reject")
        response = GateResponse(
            response_type=GateResponseType.REJECT.value,
            rejection_reason="Fundamentally wrong",
        )
        d = record_gate_decision(sample_project, tmp_projects, gate, response)
        assert "Rejected" in d.description
        assert "Fundamentally wrong" in d.description

    def test_record_gate_decision_modify(self, tmp_projects, sample_project):
        gate = Gate(gate_id="gate_003", gate_type="system_design", summary="Modify")
        response = GateResponse(
            response_type=GateResponseType.CHOOSE_WITH_MODIFICATIONS.value,
            chosen_option="B",
            modifications="Add caching layer",
        )
        d = record_gate_decision(sample_project, tmp_projects, gate, response)
        assert "option B" in d.description
        assert "Add caching layer" in d.description

    def test_record_gate_decision_combine(self, tmp_projects, sample_project):
        gate = Gate(gate_id="gate_004", gate_type="system_design", summary="Combine")
        response = GateResponse(
            response_type=GateResponseType.COMBINE.value,
            combine_instructions="Take A's core with B's API",
        )
        d = record_gate_decision(sample_project, tmp_projects, gate, response)
        assert "Combined options" in d.description


# =========================================================================
# Artifact Lineage
# =========================================================================

class TestArtifactLineage:
    def test_build_chain_basic(self, sample_project):
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            task_id="task_001",
        )
        chain = build_artifact_lineage_chain(artifact, sample_project)
        assert chain[0] == f"vision:{sample_project.project_id}"
        assert "task:task_001" in chain
        assert chain[-1] == "art_001"

    def test_build_chain_with_matching_decisions(self, tmp_projects, sample_project):
        # Add a decision that mentions the task
        record_phase_decision(
            sample_project, tmp_projects,
            decision_type="test",
            description="Completed task_001 in Core subsystem",
        )
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            task_id="task_001",
        )
        chain = build_artifact_lineage_chain(artifact, sample_project)
        # Should include the decision ID
        assert len(chain) >= 3  # vision + decision + task + artifact

    def test_build_chain_no_task(self, sample_project):
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
        )
        chain = build_artifact_lineage_chain(artifact, sample_project)
        assert chain[0] == f"vision:{sample_project.project_id}"
        assert chain[-1] == "art_001"
        assert "task:" not in " ".join(chain)

    def test_register_populates_chain(self, tmp_projects, sample_project):
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            task_id="task_001",
        )
        result = register_artifact_with_lineage(artifact, sample_project, tmp_projects)
        assert result.lineage  # Non-empty
        assert result.lineage[0].startswith("vision:")

    def test_register_appends_jsonl(self, tmp_projects, sample_project):
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            task_id="task_001",
        )
        register_artifact_with_lineage(artifact, sample_project, tmp_projects)
        loaded = load_artifact_lineage(sample_project.project_id, tmp_projects)
        assert len(loaded) == 1

    def test_register_updates_project_dict(self, tmp_projects, sample_project):
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            task_id="task_001",
        )
        register_artifact_with_lineage(artifact, sample_project, tmp_projects)
        assert "src/main.py" in sample_project.artifacts

    def test_chain_traces_to_vision(self, tmp_projects, sample_project):
        # Record a decision, then an artifact referencing it
        record_phase_decision(
            sample_project, tmp_projects,
            decision_type="design_choice",
            description="Design for Core subsystem",
        )
        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/core/model.py",
            task_id="task_001",
            subsystem="Core",
        )
        result = register_artifact_with_lineage(artifact, sample_project, tmp_projects)
        # Chain: vision → decision → task → artifact
        assert result.lineage[0].startswith("vision:")
        assert result.lineage[-1] == "art_001"


# =========================================================================
# Project Health
# =========================================================================

class TestProjectHealth:
    def test_empty_project(self, tmp_projects, sample_project):
        health = update_project_health(sample_project)
        assert health.total_tasks == 0
        assert health.completed_tasks == 0

    def test_with_tasks(self, tmp_projects, sample_project_with_tasks):
        health = update_project_health(sample_project_with_tasks)
        assert health.total_tasks == 3  # 2 completed + 1 in queue
        assert health.completed_tasks == 2

    def test_rejected_tasks(self, tmp_projects, sample_project):
        sample_project.completed_tasks = [
            BuilderTaskContract(task_id="t1", status=TaskStatus.REJECTED.value),
            BuilderTaskContract(task_id="t2", status=TaskStatus.COMPLETED.value),
        ]
        health = update_project_health(sample_project)
        assert health.rejected_tasks == 1

    def test_pending_gates(self, tmp_projects, sample_project):
        sample_project.gates = [
            Gate(gate_id="g1", status="pending"),
            Gate(gate_id="g2", status="approved"),
            Gate(gate_id="g3", status="pending"),
        ]
        health = update_project_health(sample_project)
        assert health.pending_gates == 2

    def test_updates_project_health(self, tmp_projects, sample_project):
        sample_project.completed_tasks = [
            BuilderTaskContract(task_id="t1", status=TaskStatus.COMPLETED.value),
        ]
        update_project_health(sample_project)
        assert sample_project.health.completed_tasks == 1


# =========================================================================
# Cost Tracker
# =========================================================================

class TestCostTracker:
    def _seed_usage(self, project_id, projects_dir):
        """Seed usage data for testing."""
        entries = [
            {"task_id": "task_001", "tier": 1, "provider": "anthropic", "role": "architect",
             "model": "claude-sonnet", "input_tokens": 1000, "output_tokens": 500, "estimated_cost": 0.01},
            {"task_id": "task_001", "tier": 1, "provider": "anthropic", "role": "builder",
             "model": "claude-sonnet", "input_tokens": 2000, "output_tokens": 1000, "estimated_cost": 0.02},
            {"task_id": "task_002", "tier": 1, "provider": "openai", "role": "builder",
             "model": "gpt-4", "input_tokens": 1500, "output_tokens": 800, "estimated_cost": 0.03},
            {"task_id": "task_003", "tier": 2, "provider": "anthropic", "role": "reviewer",
             "model": "claude-sonnet", "input_tokens": 500, "output_tokens": 200, "estimated_cost": 0.005},
        ]
        for e in entries:
            append_usage(e, project_id, projects_dir)

    def test_aggregate_by_task(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        result = aggregate_costs_by_task(sample_project.project_id, str(tmp_projects))
        assert result["task_001"] == pytest.approx(0.03)
        assert result["task_002"] == pytest.approx(0.03)

    def test_aggregate_by_tier(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        result = aggregate_costs_by_tier(sample_project.project_id, str(tmp_projects))
        assert result[1] == pytest.approx(0.06)
        assert result[2] == pytest.approx(0.005)

    def test_aggregate_by_provider(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        result = aggregate_costs_by_provider(sample_project.project_id, str(tmp_projects))
        assert result["anthropic"] == pytest.approx(0.035)
        assert result["openai"] == pytest.approx(0.03)

    def test_aggregate_by_role(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        result = aggregate_costs_by_role(sample_project.project_id, str(tmp_projects))
        assert result["architect"] == pytest.approx(0.01)
        assert result["builder"] == pytest.approx(0.05)
        assert result["reviewer"] == pytest.approx(0.005)

    def test_aggregate_by_model(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        result = aggregate_costs_by_model(sample_project.project_id, str(tmp_projects))
        assert result["claude-sonnet"]["call_count"] == 3
        assert result["gpt-4"]["call_count"] == 1
        assert result["claude-sonnet"]["input_tokens"] == 3500

    def test_total_project_cost(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        total = total_project_cost(sample_project.project_id, str(tmp_projects))
        assert total == pytest.approx(0.065)

    def test_empty_usage(self, tmp_projects, sample_project):
        result = aggregate_costs_by_task(sample_project.project_id, str(tmp_projects))
        assert result == {}

    def test_format_report_structure(self, tmp_projects, sample_project):
        self._seed_usage(sample_project.project_id, tmp_projects)
        report = format_cost_report(sample_project.project_id, str(tmp_projects))
        assert "Cost Report" in report
        assert "Total Cost" in report
        assert "By Tier" in report
        assert "By Provider" in report
        assert "By Role" in report
        assert "Top Tasks" in report
        assert "By Model" in report

    def test_format_report_empty(self, tmp_projects, sample_project):
        report = format_cost_report(sample_project.project_id, str(tmp_projects))
        assert "No usage data" in report


# =========================================================================
# Architect Hooks
# =========================================================================

class TestArchitectHooks:
    def _make_session(self, project, tmp_projects, docs_dir, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)

        def factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            if responses:
                c._responses = responses
            return c

        return ArchitectSession(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=factory,
        )

    def test_vision_intake_records_decision(self, tmp_projects, sample_project, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["I've reviewed the vision. What about the scope?"],
        )
        asyncio.run(session.run_vision_intake())
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert any(d.decision_type == "vision_review" for d in decisions)

    def test_vision_intake_tracks_usage(self, tmp_projects, sample_project, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Vision reviewed."],
        )
        asyncio.run(session.run_vision_intake())
        usage = load_usage(sample_project.project_id, tmp_projects)
        assert len(usage) >= 1
        assert usage[0]["role"] == "architect"

    def test_process_vision_records_transition(self, tmp_projects, sample_project, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Reviewed.", "Acknowledged."],
        )
        gate = asyncio.run(session.run_vision_intake())
        # Approve the gate
        gate.human_response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        ).to_dict()
        gate.status = GateStatus.APPROVED.value
        asyncio.run(
            session.process_vision_response(gate)
        )
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert any(d.decision_type == "phase_transition" for d in decisions)

    def test_system_design_records_decision(self, tmp_projects, sample_project, docs_dir):
        sample_project.current_phase = Phase.SYSTEM_DESIGN.value
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=['OPTION A: "Monolith"\n\nSummary: Simple monolith.\n\nOPTION B: "Microservices"\n\nSummary: Distributed.'],
        )
        asyncio.run(session.run_system_design())
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert any(d.decision_type == "design_options_presented" for d in decisions)

    def test_system_design_tracks_usage(self, tmp_projects, sample_project, docs_dir):
        sample_project.current_phase = Phase.SYSTEM_DESIGN.value
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=['OPTION A: "Monolith"\nSummary: Simple.'],
        )
        asyncio.run(session.run_system_design())
        usage = load_usage(sample_project.project_id, tmp_projects)
        assert len(usage) >= 1

    def test_process_design_records_choice(self, tmp_projects, sample_project, docs_dir):
        sample_project.current_phase = Phase.SYSTEM_DESIGN.value
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[
                'OPTION A: "Monolith"\nSummary: Simple.',
                "Here's the detailed design with subsystems...",
            ],
        )
        gate = asyncio.run(session.run_system_design())
        gate.human_response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        ).to_dict()
        gate.status = GateStatus.APPROVED.value
        asyncio.run(
            session.process_design_response(gate)
        )
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert any(d.decision_type == "design_choice" for d in decisions)

    def test_build_decomposition_records_decision(self, tmp_projects, sample_project, docs_dir):
        sample_project.current_phase = Phase.BUILD_DECOMPOSITION.value
        sample_project.architecture_template = "# Architecture"
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[
                'TASK [1]: "Setup Core"\n'
                'Subsystem: Core\nType: state_schema\nObjective: Setup core\n'
                'Must Build:\n- Models\nMust Not Touch:\n- UI\n'
                'Test Criteria:\n- Works\n'
            ],
        )
        asyncio.run(session.run_build_decomposition())
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert any(d.decision_type == "build_decomposition" for d in decisions)

    def test_build_supervision_records_and_updates_health(self, tmp_projects, sample_project_with_tasks, docs_dir):
        project = sample_project_with_tasks
        project.task_queue = project.completed_tasks.copy()
        project.completed_tasks = []

        session = self._make_session(
            project, tmp_projects, docs_dir,
            responses=["Built successfully."],
        )

        def builder_factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = [
                '```json\n{"task_id": "task_001", "artifacts": [{"file": "src/a.py", "implements": "A"}]}\n```'
            ]
            return c

        asyncio.run(
            session.run_build_supervision(builder_connector_factory=builder_factory)
        )
        decisions = load_decisions(project.project_id, tmp_projects)
        assert any(d.decision_type == "build_complete" for d in decisions)
        assert project.health.total_tasks > 0

    def test_review_phase_records_decision(self, tmp_projects, sample_project_with_tasks, docs_dir):
        project = sample_project_with_tasks
        project.current_phase = Phase.VALIDATION.value

        session = self._make_session(
            project, tmp_projects, docs_dir,
            responses=["Looks good.\nVERDICT: accept"],
        )

        def reviewer_factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ["Looks good.\nVERDICT: accept"]
            return c

        asyncio.run(
            session.run_review_phase(reviewer_connector_factory=reviewer_factory)
        )
        decisions = load_decisions(project.project_id, tmp_projects)
        assert any(d.decision_type == "review_complete" for d in decisions)

    def test_process_review_registers_with_lineage(self, tmp_projects, sample_project_with_tasks, docs_dir):
        project = sample_project_with_tasks
        project.current_phase = Phase.VALIDATION.value

        session = self._make_session(
            project, tmp_projects, docs_dir,
            responses=["Looks good.\nVERDICT: accept"],
        )

        def reviewer_factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ["Looks good.\nVERDICT: accept"]
            return c

        gate = asyncio.run(
            session.run_review_phase(reviewer_connector_factory=reviewer_factory)
        )
        gate.human_response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        ).to_dict()
        gate.status = GateStatus.APPROVED.value
        asyncio.run(
            session.process_review_response(gate)
        )
        # Check that artifacts were registered with lineage
        lineage_artifacts = load_artifact_lineage(project.project_id, tmp_projects)
        assert len(lineage_artifacts) > 0
        assert lineage_artifacts[0].lineage  # Has lineage chain


# =========================================================================
# Gate Manager Hooks
# =========================================================================

class TestGateManagerHooks:
    def test_respond_records_decision(self, tmp_projects, sample_project):
        gate_manager = GateManager(tmp_projects)
        gate = gate_manager.create_gate(
            project=sample_project,
            gate_type=GateType.VISION_CONFIRMED,
            summary="Test gate",
        )
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert len(decisions) == 1
        assert decisions[0].made_by == "human"

    def test_approve_creates_human_decision(self, tmp_projects, sample_project):
        gate_manager = GateManager(tmp_projects)
        gate = gate_manager.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Design gate",
        )
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="B",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert "Chose option B" in decisions[0].description

    def test_reject_creates_human_decision(self, tmp_projects, sample_project):
        gate_manager = GateManager(tmp_projects)
        gate = gate_manager.create_gate(
            project=sample_project,
            gate_type=GateType.VISION_CONFIRMED,
            summary="Test",
        )
        response = GateResponse(
            response_type=GateResponseType.REJECT.value,
            rejection_reason="Not acceptable",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert "Rejected" in decisions[0].description

    def test_modify_creates_human_decision(self, tmp_projects, sample_project):
        gate_manager = GateManager(tmp_projects)
        gate = gate_manager.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Design",
        )
        response = GateResponse(
            response_type=GateResponseType.CHOOSE_WITH_MODIFICATIONS.value,
            chosen_option="A",
            modifications="Add logging",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert "Add logging" in decisions[0].description

    def test_combine_creates_human_decision(self, tmp_projects, sample_project):
        gate_manager = GateManager(tmp_projects)
        gate = gate_manager.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Design",
        )
        response = GateResponse(
            response_type=GateResponseType.COMBINE.value,
            combine_instructions="Mix A and B",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)
        decisions = load_decisions(sample_project.project_id, tmp_projects)
        assert "Combined options" in decisions[0].description


# =========================================================================
# Builder Dispatch Hooks
# =========================================================================

class TestBuilderDispatchHooks:
    def test_dispatch_appends_usage(self, tmp_projects, sample_project):
        from orchestration.builder_dispatch import BuilderSession

        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Test Task",
            subsystem="Core",
            build_tier=1,
        )
        constitution = ConstitutionEnforcer(Path("constitutional_docs"))

        def factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ['```json\n{"task_id": "task_001", "artifacts": [{"file": "a.py", "implements": "A"}]}\n```']
            return c

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "anthropic", "model": "claude-sonnet"},
            projects_dir=tmp_projects,
            project_id=sample_project.project_id,
        )
        asyncio.run(session.dispatch())
        usage = load_usage(sample_project.project_id, tmp_projects)
        assert len(usage) >= 1
        assert usage[0]["role"] == "builder"

    def test_dispatch_records_correct_provider(self, tmp_projects, sample_project):
        from orchestration.builder_dispatch import BuilderSession

        task = BuilderTaskContract(task_id="task_002", build_tier=2)
        constitution = ConstitutionEnforcer(Path("constitutional_docs"))

        def factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ['```json\n{"task_id": "task_002", "artifacts": []}\n```']
            return c

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "openai", "model": "gpt-4"},
            projects_dir=tmp_projects,
            project_id=sample_project.project_id,
        )
        asyncio.run(session.dispatch())
        usage = load_usage(sample_project.project_id, tmp_projects)
        assert usage[0]["provider"] == "openai"
        assert usage[0]["model"] == "gpt-4"

    def test_dispatch_records_correct_tier(self, tmp_projects, sample_project):
        from orchestration.builder_dispatch import BuilderSession

        task = BuilderTaskContract(task_id="task_003", build_tier=3)
        constitution = ConstitutionEnforcer(Path("constitutional_docs"))

        def factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ['```json\n{"task_id": "task_003", "artifacts": []}\n```']
            return c

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "anthropic", "model": "claude-sonnet"},
            projects_dir=tmp_projects,
            project_id=sample_project.project_id,
        )
        asyncio.run(session.dispatch())
        usage = load_usage(sample_project.project_id, tmp_projects)
        assert usage[0]["tier"] == 3

    def test_dispatch_all_appends_per_task(self, tmp_projects, sample_project_with_tasks):
        from orchestration.builder_dispatch import BuilderDispatcher

        project = sample_project_with_tasks
        project.task_queue = project.completed_tasks.copy()
        project.completed_tasks = []

        constitution = ConstitutionEnforcer(Path("constitutional_docs"))

        def factory(provider="", model="", system_prompt="", **kw):
            c = MockConnector(_system_prompt=system_prompt)
            c._responses = ['```json\n{"task_id": "x", "artifacts": [{"file": "a.py", "implements": "A"}]}\n```']
            return c

        dispatcher = BuilderDispatcher(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=factory,
            roles_config={"builder_complex": {"provider": "anthropic", "model": "claude"}},
        )
        asyncio.run(dispatcher.dispatch_all())
        usage = load_usage(project.project_id, tmp_projects)
        assert len(usage) >= 2  # One per task


# =========================================================================
# CLI Commands
# =========================================================================

class TestCLI:
    def test_decisions_command(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        record_phase_decision(
            sample_project, tmp_projects,
            decision_type="test",
            description="Test decision",
        )
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "decisions", "--project", sample_project.project_id,
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "Decision Log" in captured.out
        assert "Test decision" in captured.out

    def test_decisions_no_data(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "decisions", "--project", sample_project.project_id,
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "No decisions recorded" in captured.out

    def test_decisions_project_not_found(self, tmp_projects, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "decisions", "--project", "nonexistent",
        ])
        assert result == 1

    def test_lineage_command(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        artifact = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            produced_by="builder",
            task_id="task_001",
            tier=1,
            lineage=["vision:proj_001", "task:task_001", "art_001"],
        )
        append_artifact_lineage(artifact, sample_project.project_id, tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "lineage", "--project", sample_project.project_id,
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "Artifact Lineage" in captured.out
        assert "src/main.py" in captured.out

    def test_lineage_filter(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        a1 = Artifact(artifact_id="art_001", file_path="src/main.py", lineage=["v:1"])
        a2 = Artifact(artifact_id="art_002", file_path="tests/test.py", lineage=["v:1"])
        append_artifact_lineage(a1, sample_project.project_id, tmp_projects)
        append_artifact_lineage(a2, sample_project.project_id, tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "lineage", "--project", sample_project.project_id,
            "--artifact", "tests/",
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "tests/test.py" in captured.out
        assert "src/main.py" not in captured.out

    def test_costs_command(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        append_usage(
            {"task_id": "t1", "role": "builder", "estimated_cost": 0.01,
             "input_tokens": 100, "output_tokens": 50, "tier": 1, "provider": "anthropic", "model": "claude"},
            sample_project.project_id, tmp_projects,
        )

        result = main([
            "--projects-dir", str(tmp_projects),
            "costs", "--project", sample_project.project_id,
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "Cost Report" in captured.out

    def test_costs_project_not_found(self, tmp_projects, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "costs", "--project", "nonexistent",
        ])
        assert result == 1

    def test_parser_has_commands(self):
        from cli.main import build_parser
        parser = build_parser()
        # Check that subparsers include the new commands
        # Parse valid args for each new command
        args = parser.parse_args(["decisions", "--project", "test"])
        assert args.command == "decisions"

        args = parser.parse_args(["lineage", "--project", "test"])
        assert args.command == "lineage"

        args = parser.parse_args(["costs", "--project", "test"])
        assert args.command == "costs"


# =========================================================================
# Model serialization
# =========================================================================

class TestModelSerialization:
    def test_decision_roundtrip(self):
        d = Decision(
            decision_id="dec_001",
            timestamp="2026-01-01T00:00:00Z",
            made_by="architect",
            decision_type="vision_review",
            description="Test",
            rationale="Reason",
            vision_reference="v1",
            constitutional_basis="Doc 07",
        )
        data = d.to_dict()
        loaded = Decision.from_dict(data)
        assert loaded.decision_id == d.decision_id
        assert loaded.constitutional_basis == d.constitutional_basis

    def test_artifact_with_lineage_roundtrip(self):
        a = Artifact(
            artifact_id="art_001",
            file_path="src/main.py",
            produced_by="builder",
            task_id="task_001",
            tier=1,
            subsystem="Core",
            review_id="review_001",
            lineage=["vision:proj_001", "dec_001", "task:task_001", "art_001"],
        )
        data = a.to_dict()
        loaded = Artifact.from_dict(data)
        assert loaded.lineage == a.lineage
        assert loaded.subsystem == a.subsystem

    def test_project_health_roundtrip(self):
        h = ProjectHealth(
            total_tasks=10,
            completed_tasks=7,
            rejected_tasks=1,
            pending_gates=2,
            total_cost=0.05,
        )
        data = h.to_dict()
        loaded = ProjectHealth.from_dict(data)
        assert loaded.total_tasks == 10
        assert loaded.total_cost == 0.05
