"""Tier 5 tests — Review Pipeline.

Tests use mock connectors (no real AI calls). Covers:
- Automated checks: manifest completeness, scope compliance, test coverage,
  constraint presence, incomplete items, run_automated_checks
- Review response parsing: accept/reject/revise/escalate verdict, no verdict, with notes
- Integration checks: interface matching, dependency satisfaction, duplicate artifacts
- Verdict composition: all pass, automated fail, architect revise/reject/escalate, integration issues
- ReviewEngine: review_task all accept, automated reject skips AI, AI revise,
  integration issues, saves result, review_all, skips already reviewed, empty,
  uses reviewer role, creates separate connector
- ArchitectSession review phase: creates gate, all accepted summary, mixed verdicts,
  escalation gate, journal entry, saves project, custom factory, process_review_response
- Constitution validation: clean output, scope violation, multiple violations, no restrictions
- Review persistence: save/load roundtrip, load empty, load nonexistent
- CLI: review command, requires completed tasks, architect validation routing,
  review shows summary, build_supervision advances to validation
- Models: ReviewResult roundtrip, CheckResult roundtrip, ReviewVerdict values
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from orchestration.architect import ArchitectSession
from orchestration.constitution import ConstitutionEnforcer
from orchestration.gate_manager import GateManager
from orchestration.models import (
    Artifact,
    BuilderOutputManifest,
    BuilderTaskContract,
    CheckResult,
    Gate,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
    Phase,
    ReviewResult,
    ReviewVerdict,
    TaskStatus,
    VisionContract,
)
from orchestration.project_state import ProjectState, generate_id
from orchestration.review_engine import (
    ReviewEngine,
    check_constraint_presence,
    check_duplicate_artifacts,
    check_dependency_satisfaction,
    check_incomplete_items,
    check_interface_matching,
    check_manifest_completeness,
    check_scope_compliance,
    check_test_coverage,
    compose_verdict,
    load_review_results,
    run_automated_checks,
    run_integration_check,
    save_review_result,
    _build_review_prompt,
    _parse_review_response,
)


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
def sample_task():
    return BuilderTaskContract(
        task_id="task_001",
        task_name="Define Core Schema",
        subsystem="Core",
        task_type="state_schema",
        objective="Define core data models",
        scope_must_build=["Data models", "Validation rules"],
        scope_must_not_touch=["UI layer", "API endpoints"],
        test_criteria=["Models serialize", "Validation works"],
        constraints_to_enforce=["Must use immutable state"],
        interfaces_produces=["StateAPI"],
        depends_on=[],
        parallel_group=0,
        assigned_provider="builder_complex",
        status=TaskStatus.COMPLETED.value,
    )


@pytest.fixture
def sample_manifest():
    return BuilderOutputManifest(
        task_id="task_001",
        builder_session_id="session_1",
        completed_at="2026-02-06T00:00:00Z",
        artifacts=[
            {
                "file": "src/core/state.py",
                "implements": "Core state model with immutable state",
                "constraints_enforced": ["Must use immutable state"],
            },
            {
                "file": "tests/test_state.py",
                "implements": "State model tests",
            },
        ],
        incomplete=[],
        questions_for_architect=[],
    )


@pytest.fixture
def sample_project(tmp_projects):
    vision = VisionContract(
        project_name="Test Project",
        purpose="Testing Tier 5",
        raw_markdown="# Test Project\n\n## Identity\n- Purpose: Testing Tier 5",
    )
    project = ProjectState(
        project_name="Test Project",
        vision_contract=vision,
        current_tier=1,
        current_phase="validation",
        architecture_template="# Architecture\n\n## Subsystems\n- Core\n- API",
    )
    # Add completed tasks
    project.completed_tasks = [
        BuilderTaskContract(
            task_id="task_001",
            task_name="Define Core Schema",
            subsystem="Core",
            task_type="state_schema",
            objective="Define core data models",
            scope_must_build=["Data models", "Validation rules"],
            scope_must_not_touch=["UI layer"],
            test_criteria=["Models serialize"],
            depends_on=[],
            parallel_group=0,
            status=TaskStatus.COMPLETED.value,
        ),
        BuilderTaskContract(
            task_id="task_002",
            task_name="Build API Endpoints",
            subsystem="API",
            task_type="general",
            objective="Create REST endpoints",
            scope_must_build=["CRUD endpoints"],
            scope_must_not_touch=["Database internals"],
            test_criteria=["Endpoints return JSON"],
            depends_on=["task_001"],
            parallel_group=1,
            status=TaskStatus.COMPLETED.value,
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
            {"file": "tests/test_state.py", "implements": "State model tests"},
        ],
    )
    m2 = BuilderOutputManifest(
        task_id="task_002",
        builder_session_id="session_2",
        artifacts=[
            {"file": "src/api/endpoints.py", "implements": "REST endpoints"},
            {"file": "tests/test_api.py", "implements": "API tests"},
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
    session_id: str = "mock_reviewer_session"
    _responses: list = field(default_factory=list)
    _call_count: int = 0
    _system_prompt: str = ""

    async def send_message(self, message: str, **kwargs) -> dict:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Looks good. All items addressed.\n\nVERDICT: accept"
        self._call_count += 1
        self.conversation_history.append(MockMessage(role="user", content=message))
        self.conversation_history.append(MockMessage(role="assistant", content=content))
        return {"content": content, "usage": {"input": 300, "output": 150}}


def mock_connector_factory(responses: list[str] | None = None):
    """Create a factory that returns MockConnectors with specified responses."""
    connectors_created = []

    def factory(provider="mock", model="mock", system_prompt="", **kwargs):
        connector = MockConnector(
            _responses=responses or [],
            _system_prompt=system_prompt,
        )
        connectors_created.append(connector)
        return connector

    factory.connectors_created = connectors_created
    return factory


# ---------------------------------------------------------------------------
# Automated checks tests (~15)
# ---------------------------------------------------------------------------

class TestAutomatedChecks:
    def test_manifest_completeness_pass(self, sample_manifest):
        result = check_manifest_completeness(sample_manifest)
        assert result.passed is True
        assert result.check_name == "manifest_completeness"

    def test_manifest_completeness_fail_no_task_id(self):
        manifest = BuilderOutputManifest(task_id="", artifacts=[{"file": "x.py"}])
        result = check_manifest_completeness(manifest)
        assert result.passed is False
        assert "task_id" in result.message.lower()

    def test_manifest_completeness_fail_no_artifacts(self):
        manifest = BuilderOutputManifest(task_id="task_001", artifacts=[])
        result = check_manifest_completeness(manifest)
        assert result.passed is False
        assert "artifacts" in result.message.lower()

    def test_scope_compliance_pass(self, sample_manifest, sample_task):
        result = check_scope_compliance(sample_manifest, sample_task)
        assert result.passed is True

    def test_scope_compliance_fail(self, sample_task):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "src/ui layer/component.py", "implements": "UI"}],
        )
        result = check_scope_compliance(manifest, sample_task)
        assert result.passed is False
        assert "ui layer" in result.message.lower()

    def test_scope_compliance_multiple_violations(self, sample_task):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[
                {"file": "src/ui layer/component.py", "implements": "UI"},
                {"file": "src/api endpoints/route.py", "implements": "API"},
            ],
        )
        result = check_scope_compliance(manifest, sample_task)
        assert result.passed is False
        # Both violations mentioned
        assert "ui layer" in result.message.lower()
        assert "api endpoints" in result.message.lower()

    def test_scope_compliance_no_restrictions(self):
        task = BuilderTaskContract(task_id="task_001", scope_must_not_touch=[])
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "anything.py"}],
        )
        result = check_scope_compliance(manifest, task)
        assert result.passed is True

    def test_test_coverage_pass(self, sample_manifest, sample_task):
        result = check_test_coverage(sample_manifest, sample_task)
        assert result.passed is True

    def test_test_coverage_fail(self, sample_task):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "src/core/state.py", "implements": "State"}],
        )
        result = check_test_coverage(manifest, sample_task)
        assert result.passed is False
        assert "test" in result.message.lower()

    def test_test_coverage_skip_no_criteria(self):
        task = BuilderTaskContract(task_id="task_001", test_criteria=[])
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "src/main.py"}],
        )
        result = check_test_coverage(manifest, task)
        assert result.passed is True
        assert "auto-pass" in result.message.lower()

    def test_constraint_presence_pass(self, sample_manifest, sample_task):
        result = check_constraint_presence(sample_manifest, sample_task)
        assert result.passed is True

    def test_constraint_presence_soft_warning(self):
        task = BuilderTaskContract(
            task_id="task_001",
            constraints_to_enforce=["Must use encryption"],
        )
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "src/main.py", "implements": "Main module"}],
        )
        result = check_constraint_presence(manifest, task)
        # Soft check — still passes but has warning
        assert result.passed is True
        assert "warning" in result.message.lower()

    def test_incomplete_items_pass(self, sample_manifest):
        result = check_incomplete_items(sample_manifest)
        assert result.passed is True

    def test_incomplete_items_fail(self):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            incomplete=[{"item": "Error handling", "reason": "Out of scope"}],
        )
        result = check_incomplete_items(manifest)
        assert result.passed is False
        assert "error handling" in result.message.lower()

    def test_run_automated_checks_all_pass(self, sample_manifest, sample_task):
        results = run_automated_checks(sample_manifest, sample_task)
        assert len(results) == 5
        assert all(r.passed for r in results)

    def test_run_automated_checks_mixed(self, sample_task):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[{"file": "src/main.py", "implements": "Main"}],
            incomplete=[{"item": "Tests", "reason": "Not done"}],
        )
        results = run_automated_checks(manifest, sample_task)
        assert len(results) == 5
        # Some pass, some fail
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        assert len(passed) > 0
        assert len(failed) > 0


# ---------------------------------------------------------------------------
# Review response parsing tests (~6)
# ---------------------------------------------------------------------------

class TestReviewParsing:
    def test_parse_accept_verdict(self):
        text = "Everything looks good.\n\nVERDICT: accept"
        notes, verdict = _parse_review_response(text)
        assert verdict == "accept"
        assert "looks good" in notes.lower()

    def test_parse_reject_verdict(self):
        text = "Missing key functionality.\n\nVERDICT: reject"
        notes, verdict = _parse_review_response(text)
        assert verdict == "reject"

    def test_parse_revise_verdict(self):
        text = "Needs some changes.\n\nVERDICT: revise"
        notes, verdict = _parse_review_response(text)
        assert verdict == "revise"

    def test_parse_escalate_verdict(self):
        text = "This is beyond scope.\n\nVERDICT: escalate"
        notes, verdict = _parse_review_response(text)
        assert verdict == "escalate"

    def test_parse_no_verdict_defaults_accept(self):
        text = "Everything seems fine, good work overall."
        notes, verdict = _parse_review_response(text)
        assert verdict == "accept"
        assert notes == text

    def test_parse_verdict_with_notes(self):
        text = (
            "The implementation is solid. Good test coverage.\n"
            "Minor: consider adding docstrings.\n\n"
            "VERDICT: accept"
        )
        notes, verdict = _parse_review_response(text)
        assert verdict == "accept"
        assert "solid" in notes.lower()
        assert "docstrings" in notes.lower()


# ---------------------------------------------------------------------------
# Integration checks tests (~8)
# ---------------------------------------------------------------------------

class TestIntegrationChecks:
    def test_interface_matching_pass(self, sample_manifest, sample_task):
        issues = check_interface_matching(sample_manifest, sample_task)
        assert issues == []

    def test_interface_matching_fail(self, sample_task):
        manifest = BuilderOutputManifest(task_id="task_001", artifacts=[])
        issues = check_interface_matching(manifest, sample_task)
        assert len(issues) == 1
        assert "interfaces_produces" in issues[0]

    def test_dependency_satisfaction_pass(self, sample_task, tmp_projects):
        project = ProjectState(
            completed_tasks=[{"task_id": "dep_001", "task_name": "Dep"}]
        )
        task = BuilderTaskContract(task_id="task_002", depends_on=["dep_001"])
        issues = check_dependency_satisfaction(task, project)
        assert issues == []

    def test_dependency_satisfaction_fail(self, tmp_projects):
        project = ProjectState(completed_tasks=[])
        task = BuilderTaskContract(task_id="task_002", depends_on=["dep_001"])
        issues = check_dependency_satisfaction(task, project)
        assert len(issues) == 1
        assert "dep_001" in issues[0]

    def test_duplicate_artifacts_none(self, sample_manifest):
        other = BuilderOutputManifest(
            task_id="task_002",
            artifacts=[{"file": "src/api/routes.py"}],
        )
        issues = check_duplicate_artifacts(sample_manifest, [sample_manifest, other])
        assert issues == []

    def test_duplicate_artifacts_detected(self, sample_manifest):
        other = BuilderOutputManifest(
            task_id="task_002",
            artifacts=[{"file": "src/core/state.py"}],  # Same as sample_manifest
        )
        issues = check_duplicate_artifacts(sample_manifest, [sample_manifest, other])
        assert len(issues) == 1
        assert "state.py" in issues[0]

    def test_run_integration_check_clean(self, sample_manifest, sample_task, tmp_projects):
        project = ProjectState(completed_tasks=[])
        # No depends_on, has artifacts, no duplicates
        task = BuilderTaskContract(
            task_id="task_001",
            interfaces_produces=["StateAPI"],
        )
        issues = run_integration_check(sample_manifest, task, project, [sample_manifest])
        assert issues == []

    def test_run_integration_check_mixed(self, tmp_projects):
        project = ProjectState(completed_tasks=[])
        task = BuilderTaskContract(
            task_id="task_002",
            depends_on=["dep_missing"],
            interfaces_produces=["API"],
        )
        manifest = BuilderOutputManifest(task_id="task_002", artifacts=[])
        issues = run_integration_check(manifest, task, project, [manifest])
        assert len(issues) >= 2  # dependency + interface


# ---------------------------------------------------------------------------
# Verdict composition tests (~5)
# ---------------------------------------------------------------------------

class TestVerdictComposition:
    def test_all_pass_accept(self):
        checks = [CheckResult(check_name="c1", passed=True)]
        verdict = compose_verdict(checks, "Good", "accept", [])
        assert verdict == "accept"

    def test_automated_fail_reject(self):
        checks = [CheckResult(check_name="c1", passed=False, message="Missing artifacts")]
        verdict = compose_verdict(checks, "", "accept", [])
        assert verdict == "reject"

    def test_architect_revise(self):
        checks = [CheckResult(check_name="c1", passed=True)]
        verdict = compose_verdict(checks, "Needs changes", "revise", [])
        assert verdict == "revise"

    def test_architect_escalate(self):
        checks = [CheckResult(check_name="c1", passed=True)]
        verdict = compose_verdict(checks, "Beyond scope", "escalate", [])
        assert verdict == "escalate"

    def test_integration_issues_revise(self):
        checks = [CheckResult(check_name="c1", passed=True)]
        verdict = compose_verdict(checks, "", "accept", ["Duplicate artifact found"])
        assert verdict == "revise"


# ---------------------------------------------------------------------------
# ReviewEngine tests (~10)
# ---------------------------------------------------------------------------

class TestReviewEngine:
    def _make_engine(self, project, tmp_projects, docs_dir, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory(responses)
        return ReviewEngine(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )

    def test_review_task_all_accept(
        self, sample_project, tmp_projects, docs_dir, sample_manifest
    ):
        engine = self._make_engine(sample_project, tmp_projects, docs_dir)
        task = sample_project.completed_tasks[0]
        result = asyncio.run(
            engine.review_task(sample_manifest, task, [sample_manifest])
        )
        assert result.verdict == "accept"
        assert result.task_id == "task_001"

    def test_review_task_automated_reject_skips_ai(
        self, sample_project, tmp_projects, docs_dir
    ):
        """If Stage 1 fails critically, AI review is skipped."""
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[],  # Will fail manifest completeness
        )
        # Use a factory that tracks calls
        factory = mock_connector_factory()
        engine = ReviewEngine(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=ConstitutionEnforcer(docs_dir),
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )
        task = sample_project.completed_tasks[0]
        result = asyncio.run(engine.review_task(manifest, task, [manifest]))

        assert result.verdict == "reject"
        # No connectors should have been created (AI was skipped)
        assert len(factory.connectors_created) == 0

    def test_review_task_ai_revise(
        self, sample_project, tmp_projects, docs_dir
    ):
        engine = self._make_engine(
            sample_project, tmp_projects, docs_dir,
            responses=["Needs improvements.\n\nVERDICT: revise"],
        )
        task = sample_project.completed_tasks[0]
        manifest = BuilderOutputManifest(
            task_id="task_001",
            artifacts=[
                {"file": "src/core/state.py", "implements": "State"},
                {"file": "tests/test_state.py", "implements": "Tests"},
            ],
        )
        result = asyncio.run(engine.review_task(manifest, task, [manifest]))
        assert result.verdict == "revise"

    def test_review_task_integration_issues(
        self, sample_project, tmp_projects, docs_dir
    ):
        """Integration issues should result in REVISE."""
        task = BuilderTaskContract(
            task_id="task_003",
            task_name="Missing Dep",
            depends_on=["nonexistent_task"],
            status=TaskStatus.COMPLETED.value,
        )
        manifest = BuilderOutputManifest(
            task_id="task_003",
            artifacts=[
                {"file": "src/module.py", "implements": "Module"},
                {"file": "tests/test_module.py", "implements": "Tests"},
            ],
        )
        engine = self._make_engine(sample_project, tmp_projects, docs_dir)
        result = asyncio.run(engine.review_task(manifest, task, [manifest]))
        assert result.verdict == "revise"
        assert len(result.integration_issues) > 0

    def test_review_task_saves_result(
        self, sample_project, tmp_projects, docs_dir, sample_manifest
    ):
        engine = self._make_engine(sample_project, tmp_projects, docs_dir)
        task = sample_project.completed_tasks[0]
        result = asyncio.run(
            engine.review_task(sample_manifest, task, [sample_manifest])
        )

        # Check that review was saved to disk
        reviews_dir = tmp_projects / sample_project.project_id / "reviews"
        assert reviews_dir.is_dir()
        review_files = list(reviews_dir.glob("*.json"))
        assert len(review_files) >= 1

    def test_review_all_multiple_tasks(
        self, sample_project, tmp_projects, docs_dir
    ):
        engine = self._make_engine(sample_project, tmp_projects, docs_dir)
        results = asyncio.run(engine.review_all())
        assert len(results) == 2  # Two completed tasks
        task_ids = {r.task_id for r in results}
        assert "task_001" in task_ids
        assert "task_002" in task_ids

    def test_review_all_skips_already_reviewed(
        self, sample_project, tmp_projects, docs_dir
    ):
        # First run
        engine = self._make_engine(sample_project, tmp_projects, docs_dir)
        results1 = asyncio.run(engine.review_all())
        assert len(results1) == 2

        # Second run — should return existing reviews without re-reviewing
        engine2 = self._make_engine(sample_project, tmp_projects, docs_dir)
        results2 = asyncio.run(engine2.review_all())
        assert len(results2) == 2  # Same count (includes loaded existing)

    def test_review_all_empty_completed(self, tmp_projects, docs_dir):
        project = ProjectState(
            project_name="Empty",
            current_phase="validation",
        )
        project.save(tmp_projects)
        engine = self._make_engine(project, tmp_projects, docs_dir)
        results = asyncio.run(engine.review_all())
        assert results == []

    def test_review_uses_reviewer_role(
        self, sample_project, tmp_projects, docs_dir
    ):
        """Verify that reviewer connector uses reviewer role config."""
        created_with = {}

        def tracking_factory(provider="", model="", system_prompt="", **kwargs):
            created_with["provider"] = provider
            created_with["model"] = model
            return MockConnector(_system_prompt=system_prompt)

        engine = ReviewEngine(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=ConstitutionEnforcer(docs_dir),
            connector_factory=tracking_factory,
            role_config={"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
        )
        asyncio.run(engine.review_all())

        assert created_with.get("provider") == "anthropic"
        assert created_with.get("model") == "claude-sonnet-4-5-20250929"

    def test_review_creates_separate_connector(
        self, sample_project, tmp_projects, docs_dir
    ):
        """Each review should create a fresh connector."""
        factory = mock_connector_factory()
        engine = ReviewEngine(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=ConstitutionEnforcer(docs_dir),
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )
        asyncio.run(engine.review_all())

        # Should have created a connector for each task (2 tasks)
        assert len(factory.connectors_created) == 2


# ---------------------------------------------------------------------------
# ArchitectSession review phase tests (~8)
# ---------------------------------------------------------------------------

class TestArchitectReviewPhase:
    def _make_session(self, project, tmp_projects, docs_dir, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        factory = mock_connector_factory(responses)
        return ArchitectSession(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )

    def test_creates_gate(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_review_phase())
        assert gate is not None
        assert gate.status == "pending"

    def test_all_accepted_summary(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_review_phase())
        assert "2 tasks reviewed" in gate.summary
        assert "Accepted: 2" in gate.summary

    def test_mixed_verdicts(self, sample_project, tmp_projects, docs_dir):
        # First task accept, second task revise
        responses_cycle = [0]

        def cycling_factory(provider="", model="", system_prompt="", **kwargs):
            idx = responses_cycle[0]
            responses_cycle[0] += 1
            if idx == 0:
                resp = "Good.\n\nVERDICT: accept"
            else:
                resp = "Needs work.\n\nVERDICT: revise"
            return MockConnector(_responses=[resp], _system_prompt=system_prompt)

        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=cycling_factory,
            role_config={"provider": "mock", "model": "mock"},
        )
        gate = asyncio.run(session.run_review_phase())
        assert "Accepted: 1" in gate.summary
        assert "Need revision: 1" in gate.summary

    def test_escalation_gate(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Beyond scope.\n\nVERDICT: escalate"],
        )
        gate = asyncio.run(session.run_review_phase())
        assert gate.gate_type == GateType.SCOPE_CHANGE.value

    def test_journal_entry(self, sample_project, tmp_projects, docs_dir):
        from orchestration.journal import journal_path_for_project, load_entries

        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_review_phase())

        jpath = journal_path_for_project(sample_project.project_id, tmp_projects)
        entries = load_entries(jpath)
        assert len(entries) >= 1
        last_entry = entries[-1].lower()
        assert "review" in last_entry or "accepted" in last_entry

    def test_saves_project(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_review_phase())

        reloaded = ProjectState.load(sample_project.project_id, tmp_projects)
        assert reloaded.current_phase == "validation"
        assert reloaded.pending_gate is not None

    def test_custom_factory(self, sample_project, tmp_projects, docs_dir):
        """Verify that a separate reviewer factory can be injected."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        reviewer_factory = mock_connector_factory()
        architect_factory = mock_connector_factory()

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=architect_factory,
            role_config={"provider": "mock", "model": "mock"},
        )
        gate = asyncio.run(session.run_review_phase(
            reviewer_connector_factory=reviewer_factory,
        ))

        assert gate is not None
        # Reviewer factory should have been used (2 tasks)
        assert len(reviewer_factory.connectors_created) == 2
        # Architect factory should NOT have been used for reviews
        assert len(architect_factory.connectors_created) == 0

    def test_process_review_response_registers_artifacts(
        self, sample_project, tmp_projects, docs_dir
    ):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_review_phase())

        # Simulate gate approval
        gate.status = GateStatus.APPROVED.value
        gate.human_response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        ).to_dict()

        results = asyncio.run(session.process_review_response(gate))

        # Accepted tasks should have artifacts registered
        assert len(sample_project.artifacts) > 0
        assert any("state.py" in path for path in sample_project.artifacts)


# ---------------------------------------------------------------------------
# Constitution validation tests (~4)
# ---------------------------------------------------------------------------

class TestConstitutionValidation:
    def test_clean_output(self, docs_dir):
        constitution = ConstitutionEnforcer(docs_dir)
        task = BuilderTaskContract(
            task_id="task_001",
            scope_must_not_touch=["UI layer", "Database"],
        )
        result = constitution.validate_builder_output(
            "Here is the state model implementation.", task
        )
        assert result["valid"] is True
        assert result["violations"] == []

    def test_scope_violation(self, docs_dir):
        constitution = ConstitutionEnforcer(docs_dir)
        task = BuilderTaskContract(
            task_id="task_001",
            scope_must_not_touch=["UI layer"],
        )
        result = constitution.validate_builder_output(
            "I also modified the UI layer for display.", task
        )
        assert result["valid"] is False
        assert len(result["violations"]) == 1
        assert "UI layer" in result["violations"][0]

    def test_multiple_violations(self, docs_dir):
        constitution = ConstitutionEnforcer(docs_dir)
        task = BuilderTaskContract(
            task_id="task_001",
            scope_must_not_touch=["UI layer", "Database"],
        )
        result = constitution.validate_builder_output(
            "Modified UI layer and Database for this feature.", task
        )
        assert result["valid"] is False
        assert len(result["violations"]) == 2

    def test_no_restrictions(self, docs_dir):
        constitution = ConstitutionEnforcer(docs_dir)
        task = BuilderTaskContract(
            task_id="task_001",
            scope_must_not_touch=[],
        )
        result = constitution.validate_builder_output(
            "Can reference anything.", task
        )
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# Review persistence tests (~3)
# ---------------------------------------------------------------------------

class TestReviewPersistence:
    def test_save_load_roundtrip(self, tmp_projects):
        result = ReviewResult(
            review_id="review_001",
            task_id="task_001",
            verdict="accept",
            automated_checks=[{"check_name": "completeness", "passed": True}],
            architect_notes="Looks good.",
            integration_issues=[],
            reviewed_at="2026-02-06T00:00:00Z",
        )
        save_review_result(result, "proj_1", tmp_projects)

        loaded = load_review_results("proj_1", tmp_projects)
        assert len(loaded) == 1
        assert loaded[0].review_id == "review_001"
        assert loaded[0].verdict == "accept"
        assert loaded[0].architect_notes == "Looks good."

    def test_load_empty(self, tmp_projects):
        # Create empty reviews dir
        reviews_dir = tmp_projects / "proj_empty" / "reviews"
        reviews_dir.mkdir(parents=True)
        results = load_review_results("proj_empty", tmp_projects)
        assert results == []

    def test_load_nonexistent(self, tmp_projects):
        results = load_review_results("nonexistent_project", tmp_projects)
        assert results == []


# ---------------------------------------------------------------------------
# CLI tests (~5)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_review_command_runs(
        self, sample_project, tmp_projects, docs_dir, capsys, monkeypatch
    ):
        """Review command runs the pipeline and shows results."""
        from cli.main import main

        # Patch ArchitectSession to use mock
        original_init = ArchitectSession.__init__

        def patched_init(self_session, *args, **kwargs):
            original_init(self_session, *args, **kwargs)
            self_session.connector_factory = mock_connector_factory()

        monkeypatch.setattr(ArchitectSession, "__init__", patched_init)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "review",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "review" in out.lower() or "Review" in out

    def test_review_requires_completed_tasks(self, tmp_projects, docs_dir, capsys):
        from cli.main import main

        project = ProjectState(
            project_name="No Tasks",
            current_phase="validation",
        )
        project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "review",
            "--project", project.project_id,
        ])

        assert result == 1
        err = capsys.readouterr().err
        assert "completed" in err.lower()

    def test_architect_validation_routing(
        self, sample_project, tmp_projects, docs_dir, capsys, monkeypatch
    ):
        """Architect command in validation phase prompts to run review."""
        from cli.main import main

        # Make sure no pending gate
        sample_project.pending_gate = None
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "review" in out.lower()

    def test_review_shows_summary(
        self, sample_project, tmp_projects, docs_dir, capsys, monkeypatch
    ):
        from cli.main import main

        original_init = ArchitectSession.__init__

        def patched_init(self_session, *args, **kwargs):
            original_init(self_session, *args, **kwargs)
            self_session.connector_factory = mock_connector_factory()

        monkeypatch.setattr(ArchitectSession, "__init__", patched_init)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "review",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "task_001" in out or "task_002" in out

    def test_build_supervision_advances_to_validation(
        self, tmp_projects, docs_dir, capsys, monkeypatch
    ):
        """After TIER_COMPLETE gate resolved, architect advances to validation."""
        from cli.main import main

        # Create project in build_supervision with resolved TIER_COMPLETE gate
        project = ProjectState(
            project_name="Advance Test",
            current_phase="build_supervision",
            current_tier=1,
        )
        project.completed_tasks = [
            BuilderTaskContract(task_id="t1", task_name="Task 1", status="completed"),
        ]
        project.save(tmp_projects)

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(project, GateType.TIER_COMPLETE, "Build done")
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(project, gate.gate_id, response)
        project.save(tmp_projects)

        # Patch to avoid real connector
        original_init = ArchitectSession.__init__

        def patched_init(self_session, *args, **kwargs):
            original_init(self_session, *args, **kwargs)
            self_session.connector_factory = mock_connector_factory()

        monkeypatch.setattr(ArchitectSession, "__init__", patched_init)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "validation" in out.lower() or "review" in out.lower()

        # Verify phase changed
        reloaded = ProjectState.load(project.project_id, tmp_projects)
        assert reloaded.current_phase == "validation"


# ---------------------------------------------------------------------------
# Model tests (~3)
# ---------------------------------------------------------------------------

class TestModels:
    def test_review_result_roundtrip(self):
        result = ReviewResult(
            review_id="review_001",
            task_id="task_001",
            verdict="accept",
            automated_checks=[
                {"check_name": "completeness", "passed": True, "message": "OK"},
            ],
            architect_notes="LGTM",
            integration_issues=["Minor issue"],
            revision_instructions=None,
            escalation_reason=None,
            reviewed_at="2026-02-06T00:00:00Z",
        )
        d = result.to_dict()
        loaded = ReviewResult.from_dict(d)

        assert loaded.review_id == "review_001"
        assert loaded.verdict == "accept"
        assert loaded.architect_notes == "LGTM"
        assert loaded.integration_issues == ["Minor issue"]
        assert len(loaded.automated_checks) == 1

    def test_check_result_roundtrip(self):
        check = CheckResult(
            check_name="scope_compliance",
            passed=False,
            message="Touches restricted area",
        )
        d = check.to_dict()
        loaded = CheckResult.from_dict(d)

        assert loaded.check_name == "scope_compliance"
        assert loaded.passed is False
        assert "restricted" in loaded.message

    def test_review_verdict_values(self):
        assert ReviewVerdict.ACCEPT.value == "accept"
        assert ReviewVerdict.REJECT.value == "reject"
        assert ReviewVerdict.REVISE.value == "revise"
        assert ReviewVerdict.ESCALATE.value == "escalate"
