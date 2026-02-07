"""Tier 3 tests — Task Decomposition.

Tests use mock connectors (no real AI calls). Covers:
- TaskDecomposer: parsing, dependency resolution, provider assignment, cost estimation
- Task persistence: save/load from tasks/ directory
- ArchitectSession Phase 4: run_build_decomposition, process_decomposition_response
- CLI: architect command handles build_decomposition phase
- Integration: architecture_template → ordered task queue
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from orchestration.architect import ArchitectSession
from orchestration.constitution import ConstitutionEnforcer
from orchestration.decomposer import (
    CyclicDependencyError,
    TaskDecomposer,
    _assign_providers,
    _estimate_cost,
    _parse_task_contracts,
    _resolve_dependencies,
    load_task_contracts,
    save_task_contracts,
)
from orchestration.gate_manager import GateManager
from orchestration.models import (
    BuilderTaskContract,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
    Phase,
    TaskType,
    TierCostEstimate,
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
        project_name="Test Project",
        purpose="Testing Tier 3",
        raw_markdown="# Test Project\n\n## Identity\n- Purpose: Testing Tier 3",
    )
    project = ProjectState(
        project_name="Test Project",
        vision_contract=vision,
        current_tier=1,
        current_phase="detailed_design",
        architecture_template="# Architecture Template\n\n## Subsystems\n- Auth\n- API\n- DB",
    )
    project.save(tmp_projects)
    return project


@pytest.fixture
def roles_config():
    return {
        "architect": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
        },
        "builder_complex": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
        },
        "builder_simple": {
            "provider": "deepseek",
            "model": "deepseek-chat",
        },
    }


# ---------------------------------------------------------------------------
# Mock connector (same pattern as test_tier2)
# ---------------------------------------------------------------------------

@dataclass
class MockMessage:
    role: str = ""
    content: str = ""


@dataclass
class MockConnector:
    conversation_history: list = field(default_factory=list)
    session_id: str = "mock_session_001"
    _responses: list = field(default_factory=list)
    _call_count: int = 0

    async def send_message(self, message: str, **kwargs) -> dict:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Mock response"
        self._call_count += 1
        self.conversation_history.append(MockMessage(role="user", content=message))
        self.conversation_history.append(MockMessage(role="assistant", content=content))
        return {"content": content, "usage": {"input": 100, "output": 50}}


def mock_connector_factory(responses: list[str] | None = None):
    def factory(provider="mock", model="mock", system_prompt="", **kwargs):
        return MockConnector(_responses=responses or [])
    return factory


# ---------------------------------------------------------------------------
# Sample AI responses for decomposition
# ---------------------------------------------------------------------------

SAMPLE_DECOMPOSITION_RESPONSE = '''\
TASK [1]: "Define Core State Schema"

  Subsystem: Core
  Task type: state_schema
  Objective: Define the core data models and state structure

  Inputs:
    - Architecture Template
    - Vision Contract

  Must build:
    - Data model definitions
    - State validation rules

  Must not touch:
    - UI layer
    - External APIs

  Rules to implement:
    - All state must be serializable

  Constraints to enforce:
    - No circular references

  Interfaces receives:
    - Raw input data

  Interfaces produces:
    - Validated state objects

  Test criteria:
    - All models serialize round-trip
    - Validation catches invalid state

  Depends on: none

TASK [2]: "Implement Authentication Flow"

  Subsystem: Auth
  Task type: flow
  Objective: Build the authentication and session management flow

  Inputs:
    - Core state schema
    - Security requirements

  Must build:
    - Login flow
    - Session management
    - Token validation

  Must not touch:
    - Database schema
    - UI components

  Rules to implement:
    - Sessions expire after 24 hours

  Constraints to enforce:
    - All tokens must be cryptographically signed

  Interfaces receives:
    - User credentials

  Interfaces produces:
    - Authentication tokens

  Test criteria:
    - Login succeeds with valid credentials
    - Login fails with invalid credentials
    - Sessions expire correctly

  Depends on: 1

TASK [3]: "Build API Endpoints"

  Subsystem: API
  Task type: general
  Objective: Create REST API endpoints for all core operations

  Inputs:
    - Core state schema
    - Auth flow

  Must build:
    - CRUD endpoints
    - Input validation
    - Error handling

  Must not touch:
    - Frontend
    - Database internals

  Rules to implement:
    - All endpoints return JSON

  Constraints to enforce:
    - Rate limiting on all endpoints

  Interfaces receives:
    - HTTP requests

  Interfaces produces:
    - JSON responses

  Test criteria:
    - All endpoints return correct status codes
    - Input validation works

  Depends on: 1, 2

TASK [4]: "Create UI Components"

  Subsystem: Frontend
  Task type: ux_layer
  Objective: Build the user-facing interface components

  Inputs:
    - API endpoints
    - Design specs

  Must build:
    - Login page
    - Dashboard
    - Settings page

  Must not touch:
    - Backend logic
    - Database

  Rules to implement:
    - Responsive design

  Constraints to enforce:
    - Accessibility standards

  Interfaces receives:
    - API responses

  Interfaces produces:
    - Rendered UI

  Test criteria:
    - All pages render without errors
    - Forms validate input

  Depends on: 3

COST ESTIMATE:
  Task count: 4
  Complex tasks: 2 (state_schema, flow)
  Simple tasks: 2 (general, ux_layer)
  Cost drivers:
    - 2 complex tasks using higher-tier provider
  Savings opportunities:
    - Batch simple tasks where possible
'''

SAMPLE_THREE_TASK_RESPONSE = '''\
TASK [1]: "Schema Setup"

  Subsystem: Core
  Task type: state_schema
  Objective: Define schemas

  Test criteria:
    - Schemas validate

  Depends on: none

TASK [2]: "Logic Layer"

  Subsystem: Core
  Task type: flow
  Objective: Implement logic

  Test criteria:
    - Logic works

  Depends on: 1

TASK [3]: "UI Layer"

  Subsystem: UI
  Task type: ux_layer
  Objective: Build UI

  Test criteria:
    - UI renders

  Depends on: 1
'''


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParsing:
    def test_parse_four_tasks(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert len(tasks) == 4

    def test_parse_task_names(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        names = [t.task_name for t in tasks]
        assert "Define Core State Schema" in names
        assert "Implement Authentication Flow" in names
        assert "Build API Endpoints" in names
        assert "Create UI Components" in names

    def test_parse_task_types(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        types = [t.task_type for t in tasks]
        assert types[0] == "state_schema"
        assert types[1] == "flow"
        assert types[2] == "general"
        assert types[3] == "ux_layer"

    def test_parse_subsystem(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert tasks[0].subsystem == "Core"
        assert tasks[1].subsystem == "Auth"

    def test_parse_objective(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert "core data models" in tasks[0].objective.lower()

    def test_parse_must_build(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert len(tasks[0].scope_must_build) == 2
        assert "Data model definitions" in tasks[0].scope_must_build

    def test_parse_must_not_touch(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert "UI layer" in tasks[0].scope_must_not_touch

    def test_parse_test_criteria(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert len(tasks[0].test_criteria) == 2
        assert len(tasks[1].test_criteria) == 3

    def test_parse_interfaces(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert "Raw input data" in tasks[0].interfaces_receives
        assert "Validated state objects" in tasks[0].interfaces_produces

    def test_parse_dependencies_none(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert tasks[0].depends_on == []

    def test_parse_dependencies_single(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        # Task 2 depends on task 1 → __task_index_0
        assert "__task_index_0" in tasks[1].depends_on

    def test_parse_dependencies_multiple(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        # Task 3 depends on tasks 1 and 2 → __task_index_0, __task_index_1
        assert "__task_index_0" in tasks[2].depends_on
        assert "__task_index_1" in tasks[2].depends_on

    def test_parse_empty_text(self):
        assert _parse_task_contracts("") == []

    def test_parse_no_tasks(self):
        assert _parse_task_contracts("Some random text without task headers") == []

    def test_parse_invalid_task_type_defaults_to_general(self):
        text = 'TASK [1]: "Test"\n\n  Task type: nonexistent_type\n  Depends on: none\n'
        tasks = _parse_task_contracts(text)
        assert len(tasks) == 1
        assert tasks[0].task_type == "general"

    def test_parse_rules_and_constraints(self):
        tasks = _parse_task_contracts(SAMPLE_DECOMPOSITION_RESPONSE)
        assert "All state must be serializable" in tasks[0].rules_to_implement
        assert "No circular references" in tasks[0].constraints_to_enforce


# ---------------------------------------------------------------------------
# Dependency resolution tests
# ---------------------------------------------------------------------------

class TestDependencyResolution:
    def _make_tasks(self, dep_map: dict[str, list[str]]) -> list[BuilderTaskContract]:
        """Create tasks with given dependency structure.
        dep_map: {task_id: [dep_task_ids]}
        """
        tasks = []
        for tid in dep_map:
            tasks.append(BuilderTaskContract(
                task_id=tid,
                task_name=f"Task {tid}",
                depends_on=list(dep_map[tid]),
            ))
        return tasks

    def test_linear_chain(self):
        tasks = self._make_tasks({
            "t1": [],
            "t2": ["t1"],
            "t3": ["t2"],
        })
        result = _resolve_dependencies(tasks)
        assert len(result) == 3
        # t1 first, t3 last
        ids = [t.task_id for t in result]
        assert ids.index("t1") < ids.index("t2") < ids.index("t3")

    def test_parallel_groups_linear(self):
        tasks = self._make_tasks({
            "t1": [],
            "t2": ["t1"],
            "t3": ["t2"],
        })
        result = _resolve_dependencies(tasks)
        groups = {t.task_id: t.parallel_group for t in result}
        assert groups["t1"] == 0
        assert groups["t2"] == 1
        assert groups["t3"] == 2

    def test_diamond_dependency(self):
        tasks = self._make_tasks({
            "t1": [],
            "t2": ["t1"],
            "t3": ["t1"],
            "t4": ["t2", "t3"],
        })
        result = _resolve_dependencies(tasks)
        groups = {t.task_id: t.parallel_group for t in result}
        assert groups["t1"] == 0
        assert groups["t2"] == 1
        assert groups["t3"] == 1  # t2 and t3 in same group
        assert groups["t4"] == 2

    def test_no_dependencies_all_group_zero(self):
        tasks = self._make_tasks({
            "t1": [],
            "t2": [],
            "t3": [],
        })
        result = _resolve_dependencies(tasks)
        assert all(t.parallel_group == 0 for t in result)

    def test_cycle_detection(self):
        tasks = self._make_tasks({
            "t1": ["t3"],
            "t2": ["t1"],
            "t3": ["t2"],
        })
        with pytest.raises(CyclicDependencyError):
            _resolve_dependencies(tasks)

    def test_self_cycle_detection(self):
        tasks = self._make_tasks({
            "t1": ["t1"],
        })
        with pytest.raises(CyclicDependencyError):
            _resolve_dependencies(tasks)

    def test_placeholder_resolution(self):
        """Test that __task_index_N placeholders are resolved to actual task IDs."""
        tasks = [
            BuilderTaskContract(task_id="task_aaa", task_name="First", depends_on=[]),
            BuilderTaskContract(task_id="task_bbb", task_name="Second", depends_on=["__task_index_0"]),
        ]
        result = _resolve_dependencies(tasks)
        # task_bbb should now depend on task_aaa
        second = next(t for t in result if t.task_id == "task_bbb")
        assert "task_aaa" in second.depends_on

    def test_empty_task_list(self):
        result = _resolve_dependencies([])
        assert result == []

    def test_unknown_dependency_preserved(self):
        """Unknown dep IDs (not in task list) should be preserved but not cause errors."""
        tasks = self._make_tasks({
            "t1": ["unknown_external"],
            "t2": [],
        })
        result = _resolve_dependencies(tasks)
        t1 = next(t for t in result if t.task_id == "t1")
        assert "unknown_external" in t1.depends_on


# ---------------------------------------------------------------------------
# Provider assignment tests
# ---------------------------------------------------------------------------

class TestProviderAssignment:
    def test_complex_type_gets_complex_provider(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema"),
            BuilderTaskContract(task_id="t2", task_type="flow"),
            BuilderTaskContract(task_id="t3", task_type="constraint"),
        ]
        result = _assign_providers(tasks, roles_config)
        for t in result:
            assert "anthropic" in t.assigned_provider

    def test_simple_type_gets_simple_provider(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="general"),
            BuilderTaskContract(task_id="t2", task_type="ux_layer"),
        ]
        result = _assign_providers(tasks, roles_config)
        for t in result:
            assert "deepseek" in t.assigned_provider

    def test_mixed_types(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema"),
            BuilderTaskContract(task_id="t2", task_type="general"),
        ]
        result = _assign_providers(tasks, roles_config)
        assert "anthropic" in result[0].assigned_provider
        assert "deepseek" in result[1].assigned_provider

    def test_no_config_uses_role_name(self):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema"),
            BuilderTaskContract(task_id="t2", task_type="general"),
        ]
        result = _assign_providers(tasks, {})
        assert result[0].assigned_provider == "builder_complex"
        assert result[1].assigned_provider == "builder_simple"

    def test_failure_recovery_is_complex(self, roles_config):
        tasks = [BuilderTaskContract(task_id="t1", task_type="failure_recovery")]
        result = _assign_providers(tasks, roles_config)
        assert "anthropic" in result[0].assigned_provider

    def test_dependency_cascade_is_complex(self, roles_config):
        tasks = [BuilderTaskContract(task_id="t1", task_type="dependency_cascade")]
        result = _assign_providers(tasks, roles_config)
        assert "anthropic" in result[0].assigned_provider


# ---------------------------------------------------------------------------
# Cost estimation tests
# ---------------------------------------------------------------------------

class TestCostEstimation:
    def test_basic_cost_estimate(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema", assigned_provider="anthropic/claude"),
            BuilderTaskContract(task_id="t2", task_type="general", assigned_provider="deepseek/chat"),
        ]
        cost = _estimate_cost(tasks, roles_config)

        assert cost.task_count == 2
        assert cost.cost_low > 0
        assert cost.cost_mid > cost.cost_low
        assert cost.cost_high > cost.cost_mid

    def test_cost_estimate_provider_mix(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema", assigned_provider="anthropic/claude"),
            BuilderTaskContract(task_id="t2", task_type="flow", assigned_provider="anthropic/claude"),
            BuilderTaskContract(task_id="t3", task_type="general", assigned_provider="deepseek/chat"),
        ]
        cost = _estimate_cost(tasks, roles_config)

        assert cost.provider_mix["anthropic/claude"] == 2
        assert cost.provider_mix["deepseek/chat"] == 1

    def test_cost_drivers_present(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema", assigned_provider="anthropic/claude"),
            BuilderTaskContract(task_id="t2", task_type="general", assigned_provider="deepseek/chat"),
        ]
        cost = _estimate_cost(tasks, roles_config)
        assert len(cost.cost_drivers) >= 1

    def test_all_complex_tasks(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="state_schema", assigned_provider="x"),
            BuilderTaskContract(task_id="t2", task_type="flow", assigned_provider="x"),
        ]
        cost = _estimate_cost(tasks, roles_config)
        assert cost.task_count == 2
        assert cost.cost_mid > 0

    def test_all_simple_tasks(self, roles_config):
        tasks = [
            BuilderTaskContract(task_id="t1", task_type="general", assigned_provider="x"),
            BuilderTaskContract(task_id="t2", task_type="ux_layer", assigned_provider="x"),
        ]
        cost = _estimate_cost(tasks, roles_config)
        assert cost.task_count == 2
        assert cost.cost_mid > 0

    def test_empty_task_list(self, roles_config):
        cost = _estimate_cost([], roles_config)
        assert cost.task_count == 0
        assert cost.cost_mid == 0.0

    def test_cost_estimate_roundtrip(self):
        cost = TierCostEstimate(
            task_count=5,
            provider_mix={"anthropic": 3, "deepseek": 2},
            cost_low=1.0,
            cost_mid=2.0,
            cost_high=4.0,
            cost_drivers=["Complex tasks"],
            savings_opportunities=["Batch simple tasks"],
        )
        d = cost.to_dict()
        loaded = TierCostEstimate.from_dict(d)
        assert loaded.task_count == 5
        assert loaded.cost_mid == 2.0
        assert loaded.provider_mix == {"anthropic": 3, "deepseek": 2}


# ---------------------------------------------------------------------------
# Task persistence tests
# ---------------------------------------------------------------------------

class TestTaskPersistence:
    def test_save_and_load(self, tmp_projects):
        project_id = "proj_test123"
        tasks = [
            BuilderTaskContract(
                task_id="task_aaa",
                task_name="First Task",
                subsystem="Core",
                task_type="state_schema",
                depends_on=[],
                parallel_group=0,
            ),
            BuilderTaskContract(
                task_id="task_bbb",
                task_name="Second Task",
                subsystem="API",
                task_type="general",
                depends_on=["task_aaa"],
                parallel_group=1,
            ),
        ]

        paths = save_task_contracts(tasks, project_id, tmp_projects)
        assert len(paths) == 2
        assert all(p.exists() for p in paths)

        loaded = load_task_contracts(project_id, tmp_projects)
        assert len(loaded) == 2
        assert loaded[0].task_name == "First Task"
        assert loaded[1].depends_on == ["task_aaa"]

    def test_save_creates_tasks_dir(self, tmp_projects):
        project_id = "proj_new"
        tasks = [BuilderTaskContract(task_id="task_xxx", task_name="Test")]
        save_task_contracts(tasks, project_id, tmp_projects)
        assert (tmp_projects / project_id / "tasks").is_dir()

    def test_load_empty_dir(self, tmp_projects):
        project_id = "proj_empty"
        (tmp_projects / project_id / "tasks").mkdir(parents=True)
        loaded = load_task_contracts(project_id, tmp_projects)
        assert loaded == []

    def test_load_nonexistent_dir(self, tmp_projects):
        loaded = load_task_contracts("nonexistent", tmp_projects)
        assert loaded == []

    def test_task_json_contains_new_fields(self, tmp_projects):
        project_id = "proj_fields"
        tasks = [
            BuilderTaskContract(
                task_id="task_f1",
                task_name="Field Test",
                depends_on=["task_other"],
                parallel_group=2,
            ),
        ]
        paths = save_task_contracts(tasks, project_id, tmp_projects)
        data = json.loads(paths[0].read_text())
        assert data["depends_on"] == ["task_other"]
        assert data["parallel_group"] == 2


# ---------------------------------------------------------------------------
# ArchitectSession Phase 4 tests
# ---------------------------------------------------------------------------

class TestArchitectPhase4:
    def _make_session(self, project, tmp_projects, docs_dir, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        return ArchitectSession(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=mock_connector_factory(responses or []),
            role_config={"provider": "mock", "model": "mock-model"},
        )

    def test_run_build_decomposition_creates_gate(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE],
        )

        gate = asyncio.run(session.run_build_decomposition())

        assert gate.gate_type == "build_decomposition"
        assert gate.status == "pending"
        assert "tasks" in gate.summary.lower() or "Tasks" in gate.summary
        assert sample_project.pending_gate is gate
        assert sample_project.current_phase == "build_decomposition"

    def test_run_build_decomposition_stores_pending_tasks(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE],
        )

        asyncio.run(session.run_build_decomposition())

        assert hasattr(session, "_pending_tasks")
        assert len(session._pending_tasks) == 4
        assert hasattr(session, "_pending_cost")
        assert session._pending_cost.task_count == 4

    def test_process_decomposition_approved(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE, "Acknowledged, proceeding."],
        )

        gate = asyncio.run(session.run_build_decomposition())

        # Approve the gate
        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        tasks = asyncio.run(session.process_decomposition_response(gate))

        assert len(tasks) == 4
        assert sample_project.current_phase == "build_supervision"
        assert len(sample_project.task_queue) == 4

    def test_process_decomposition_stores_task_jsons(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE, "Acknowledged."],
        )

        gate = asyncio.run(session.run_build_decomposition())

        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        tasks = asyncio.run(session.process_decomposition_response(gate))

        # Verify task files on disk
        loaded = load_task_contracts(sample_project.project_id, tmp_projects)
        assert len(loaded) == 4

    def test_process_decomposition_revision(self, sample_project, tmp_projects, docs_dir):
        revised_response = SAMPLE_THREE_TASK_RESPONSE
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE, revised_response],
        )

        gate = asyncio.run(session.run_build_decomposition())

        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.REVISE_AND_PROCEED.value,
            revision_feedback="Reduce to 3 tasks",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        tasks = asyncio.run(session.process_decomposition_response(gate))

        assert len(tasks) == 3
        assert sample_project.current_phase == "build_supervision"

    def test_decomposition_gate_has_cost_info(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE],
        )

        gate = asyncio.run(session.run_build_decomposition())

        assert "$" in gate.summary
        assert "4 tasks" in gate.summary

    def test_decomposition_journal_entries(self, sample_project, tmp_projects, docs_dir):
        from orchestration.journal import journal_path_for_project, load_entries

        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE, "Acknowledged."],
        )

        gate = asyncio.run(session.run_build_decomposition())

        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)
        asyncio.run(session.process_decomposition_response(gate))

        jpath = journal_path_for_project(sample_project.project_id, tmp_projects)
        entries = load_entries(jpath)
        assert len(entries) == 2  # One for decomposition, one for approval

    def test_tasks_have_unique_ids(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE],
        )

        asyncio.run(session.run_build_decomposition())

        task_ids = [t.task_id for t in session._pending_tasks]
        assert len(set(task_ids)) == len(task_ids)  # all unique
        assert all(tid.startswith("task_") for tid in task_ids)

    def test_tasks_have_build_tier(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_DECOMPOSITION_RESPONSE],
        )

        asyncio.run(session.run_build_decomposition())

        for task in session._pending_tasks:
            assert task.build_tier == sample_project.current_tier


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_architect_detailed_design_triggers_decomposition(
        self, sample_project, tmp_projects, docs_dir, capsys
    ):
        from cli.main import main

        # Set up mock connector factory by patching the session creation
        # The CLI creates its own session, so we need to test via the cmd
        # We test indirectly: with detailed_design phase, no decomp gates, it should attempt decomposition
        # Since real connector would be used, we test the gate-blocked path instead

        # Create a pending decomposition gate to test the blocked path
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            sample_project,
            GateType.BUILD_DECOMPOSITION,
            "Decomposition pending",
        )
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", sample_project.project_id,
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "approve" in out.lower() or "reject" in out.lower()

    def test_architect_build_supervision_shows_status(
        self, sample_project, tmp_projects, docs_dir, capsys
    ):
        from cli.main import main

        sample_project.current_phase = "build_supervision"
        sample_project.task_queue = [
            BuilderTaskContract(task_id="t1", task_name="Task 1"),
            BuilderTaskContract(task_id="t2", task_name="Task 2"),
        ]
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", sample_project.project_id,
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "build_supervision" in out
        assert "2 tasks" in out


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_builder_task_contract_new_fields(self):
        task = BuilderTaskContract(
            task_id="task_test",
            task_name="Test Task",
            depends_on=["task_a", "task_b"],
            parallel_group=2,
        )
        d = task.to_dict()
        assert d["depends_on"] == ["task_a", "task_b"]
        assert d["parallel_group"] == 2

        loaded = BuilderTaskContract.from_dict(d)
        assert loaded.depends_on == ["task_a", "task_b"]
        assert loaded.parallel_group == 2

    def test_builder_task_contract_defaults(self):
        task = BuilderTaskContract()
        assert task.depends_on == []
        assert task.parallel_group == 0

    def test_gate_type_build_decomposition(self):
        assert GateType.BUILD_DECOMPOSITION.value == "build_decomposition"

    def test_tier_cost_estimate_model(self):
        cost = TierCostEstimate(
            task_count=10,
            provider_mix={"anthropic": 6, "deepseek": 4},
            cost_low=0.5,
            cost_mid=1.0,
            cost_high=2.0,
            cost_drivers=["10 tasks"],
            savings_opportunities=["Batch tasks"],
        )
        d = cost.to_dict()
        loaded = TierCostEstimate.from_dict(d)
        assert loaded.task_count == 10
        assert loaded.cost_low == 0.5
        assert loaded.provider_mix == {"anthropic": 6, "deepseek": 4}


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_decomposition_flow(self, sample_project, tmp_projects, docs_dir):
        """Full flow: architecture_template → decompose → gate → approve → task queue."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=mock_connector_factory([
                SAMPLE_DECOMPOSITION_RESPONSE,
                "Acknowledged, proceeding with approved decomposition.",
            ]),
            role_config={"provider": "mock", "model": "mock-model"},
        )

        # Phase 4a: Decompose
        gate = asyncio.run(session.run_build_decomposition())
        assert gate.gate_type == "build_decomposition"
        assert gate.status == "pending"

        # Human approves
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gate_manager.respond_to_gate(sample_project, gate.gate_id, response)

        # Phase 4b: Process response
        tasks = asyncio.run(session.process_decomposition_response(gate))

        # Verify final state
        assert len(tasks) == 4
        assert sample_project.current_phase == "build_supervision"
        assert len(sample_project.task_queue) == 4

        # Verify ordering: tasks with no deps come first
        assert tasks[0].parallel_group == 0
        assert tasks[0].depends_on == []

        # Verify tasks are on disk
        loaded = load_task_contracts(sample_project.project_id, tmp_projects)
        assert len(loaded) == 4

        # Verify project state was saved
        reloaded = ProjectState.load(sample_project.project_id, tmp_projects)
        assert reloaded.current_phase == "build_supervision"
        assert len(reloaded.task_queue) == 4

    def test_decomposition_with_parallel_groups(self, sample_project, tmp_projects, docs_dir):
        """Verify parallel groups are correctly assigned for diamond dependency."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=mock_connector_factory([
                SAMPLE_THREE_TASK_RESPONSE,
                "Acknowledged.",
            ]),
            role_config={"provider": "mock", "model": "mock-model"},
        )

        gate = asyncio.run(session.run_build_decomposition())

        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        tasks = asyncio.run(session.process_decomposition_response(gate))

        # Task 1 has no deps → group 0
        # Tasks 2 and 3 both depend on 1 → group 1
        groups = {t.task_name: t.parallel_group for t in tasks}
        assert groups["Schema Setup"] == 0
        assert groups["Logic Layer"] == 1
        assert groups["UI Layer"] == 1
