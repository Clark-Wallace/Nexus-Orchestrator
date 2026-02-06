"""Tests for ConstitutionEnforcer — doc loading and context building."""

import tempfile
from pathlib import Path

import pytest

from orchestration.constitution import ConstitutionEnforcer, _extract_section
from orchestration.models import (
    BuilderTaskContract,
    Phase,
    TaskType,
    VisionContract,
)
from orchestration.project_state import ProjectState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def doc_stack_dir():
    """Use the actual constitutional_docs directory."""
    docs_path = Path(__file__).parent.parent / "constitutional_docs"
    if not docs_path.exists():
        pytest.skip("constitutional_docs directory not found")
    return docs_path


@pytest.fixture
def enforcer(doc_stack_dir):
    return ConstitutionEnforcer(doc_stack_dir)


@pytest.fixture
def sample_project():
    vc = VisionContract(
        project_name="Test Sim",
        domain="testing",
        purpose="Test the orchestrator",
        primary_questions=["Does it work?"],
        raw_markdown="# Test Sim\n\nA test vision contract.",
    )
    return ProjectState(
        project_name="Test Sim",
        vision_contract=vc,
        current_tier=1,
        current_phase=Phase.VISION_INTAKE.value,
    )


@pytest.fixture
def sample_task():
    return BuilderTaskContract(
        task_id="task_001",
        task_name="Implement power state schema",
        build_tier=1,
        subsystem="power",
        task_type=TaskType.STATE_SCHEMA.value,
        objective="Create power subsystem state model",
        verbs_used=["allocate_resource"],
    )


# ---------------------------------------------------------------------------
# Doc Loading
# ---------------------------------------------------------------------------

class TestDocLoading:
    def test_loads_all_docs(self, enforcer):
        """Should load docs 00 through 09."""
        assert len(enforcer.docs) >= 8
        for i in range(8):  # 00-07 at minimum
            assert i in enforcer.docs, f"Doc {i:02d} not loaded"

    def test_doc_content_not_empty(self, enforcer):
        for doc_num, content in enforcer.docs.items():
            assert len(content) > 0, f"Doc {doc_num:02d} is empty"

    def test_get_doc_returns_content(self, enforcer):
        doc = enforcer.get_doc(0)
        assert "Session Preamble" in doc or "Build Partner" in doc

    def test_get_doc_invalid_raises(self, enforcer):
        with pytest.raises(KeyError):
            enforcer.get_doc(99)

    def test_loaded_doc_numbers_sorted(self, enforcer):
        nums = enforcer.loaded_doc_numbers
        assert nums == sorted(nums)

    def test_nonexistent_path_raises(self):
        with pytest.raises(FileNotFoundError):
            ConstitutionEnforcer("/nonexistent/path")


# ---------------------------------------------------------------------------
# Architect Context Building
# ---------------------------------------------------------------------------

class TestArchitectContext:
    def test_always_includes_doc_07(self, enforcer, sample_project):
        ctx = enforcer.build_architect_context(sample_project)
        assert "Architect Constitution" in ctx or "AI Architect" in ctx

    def test_always_includes_vision(self, enforcer, sample_project):
        ctx = enforcer.build_architect_context(sample_project)
        assert "Test Sim" in ctx

    def test_always_includes_project_status(self, enforcer, sample_project):
        ctx = enforcer.build_architect_context(sample_project)
        assert "PROJECT STATUS" in ctx

    def test_includes_role_header(self, enforcer, sample_project):
        ctx = enforcer.build_architect_context(sample_project)
        assert "ARCHITECT ROLE" in ctx

    def test_vision_intake_loads_doc_01_summary(self, enforcer, sample_project):
        sample_project.current_phase = Phase.VISION_INTAKE.value
        ctx = enforcer.build_architect_context(sample_project)
        # Should include Doc 01 content (at least headings)
        assert "Phase-Specific Context" in ctx

    def test_system_design_loads_doc_01_full(self, enforcer, sample_project):
        sample_project.current_phase = Phase.SYSTEM_DESIGN.value
        ctx = enforcer.build_architect_context(sample_project)
        assert "Doc 01" in ctx

    def test_detailed_design_loads_docs_03_04_05(self, enforcer, sample_project):
        sample_project.current_phase = Phase.DETAILED_DESIGN.value
        ctx = enforcer.build_architect_context(sample_project)
        assert "Doc 03" in ctx
        assert "Doc 04" in ctx
        assert "Doc 05" in ctx

    def test_includes_journal_entries(self, enforcer, sample_project):
        entries = ["Entry 1: Started design", "Entry 2: Chose option B", "Entry 3: Finished tier"]
        ctx = enforcer.build_architect_context(sample_project, journal_entries=entries)
        assert "Journal" in ctx
        assert "Entry 1" in ctx

    def test_journal_limited_to_last_3(self, enforcer, sample_project):
        entries = [f"Entry {i}" for i in range(10)]
        ctx = enforcer.build_architect_context(sample_project, journal_entries=entries)
        assert "Entry 7" in ctx
        assert "Entry 9" in ctx
        # Entry 0-6 should not appear (only last 3)
        assert "Entry 6" not in ctx


# ---------------------------------------------------------------------------
# Builder Context Building
# ---------------------------------------------------------------------------

class TestBuilderContext:
    def test_always_includes_doc_00(self, enforcer, sample_task):
        ctx = enforcer.build_builder_context(sample_task)
        assert "Session Preamble" in ctx or "Doc 00" in ctx

    def test_always_includes_task_contract(self, enforcer, sample_task):
        ctx = enforcer.build_builder_context(sample_task)
        assert "BUILDER TASK CONTRACT" in ctx
        assert "task_001" in ctx
        assert "power" in ctx

    def test_includes_role_header(self, enforcer, sample_task):
        ctx = enforcer.build_builder_context(sample_task)
        assert "BUILDER ROLE" in ctx

    def test_state_schema_task_loads_doc_02(self, enforcer, sample_task):
        sample_task.task_type = TaskType.STATE_SCHEMA.value
        ctx = enforcer.build_builder_context(sample_task)
        # Should include Doc 02 section reference
        assert "Doc 02" in ctx

    def test_flow_task_loads_docs_02_03(self, enforcer):
        task = BuilderTaskContract(
            task_id="task_002",
            task_name="Implement cooling flow",
            task_type=TaskType.FLOW.value,
        )
        ctx = enforcer.build_builder_context(task)
        assert "Doc 02" in ctx
        assert "Doc 03" in ctx

    def test_constraint_task_loads_docs_02_04(self, enforcer):
        task = BuilderTaskContract(
            task_id="task_003",
            task_name="Implement capacity constraints",
            task_type=TaskType.CONSTRAINT.value,
        )
        ctx = enforcer.build_builder_context(task)
        assert "Doc 02" in ctx
        assert "Doc 04" in ctx

    def test_ux_task_loads_docs_04_05(self, enforcer):
        task = BuilderTaskContract(
            task_id="task_004",
            task_name="Build decision card UX",
            task_type=TaskType.UX_LAYER.value,
        )
        ctx = enforcer.build_builder_context(task)
        assert "Doc 05" in ctx
        assert "Doc 04" in ctx

    def test_general_task_loads_minimal_context(self, enforcer):
        task = BuilderTaskContract(
            task_id="task_005",
            task_name="General utility task",
            task_type=TaskType.GENERAL.value,
        )
        ctx = enforcer.build_builder_context(task)
        # Should have preamble and contract but no extra docs
        assert "BUILDER TASK CONTRACT" in ctx
        assert "Task-Specific Context" not in ctx

    def test_task_contract_format_includes_all_fields(self, enforcer):
        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Full task",
            build_tier=2,
            subsystem="cooling",
            objective="Build the cooling model",
            inputs=["power_schema.json"],
            scope_must_build=["CoolingState class", "flow resolver"],
            scope_must_not_touch=["power subsystem", "network layer"],
            verbs_used=["allocate_resource", "throttle_flow"],
            interfaces_receives=["power_load signal"],
            interfaces_produces=["cooling_status update"],
            test_criteria=["Schema matches spec", "Constraints are hard"],
        )
        ctx = enforcer.build_builder_context(task)
        assert "Objective:" in ctx
        assert "Inputs:" in ctx
        assert "MUST Build:" in ctx
        assert "MUST NOT Touch:" in ctx
        assert "Verbs Used:" in ctx
        assert "allocate_resource" in ctx
        assert "Test Criteria:" in ctx


# ---------------------------------------------------------------------------
# Section Extraction
# ---------------------------------------------------------------------------

class TestSectionExtraction:
    def test_extract_principles_summary(self):
        text = "# Title\n## Principle 1\nContent\n## Principle 2\nMore content"
        result = _extract_section(text, "principles_summary")
        assert "# Title" in result
        assert "## Principle 1" in result
        assert "## Principle 2" in result
        assert "Content" not in result

    def test_extract_returns_empty_for_unknown_key(self):
        result = _extract_section("some text", "nonexistent_key")
        assert result == ""

    def test_extract_state_model_section(self, enforcer):
        """If Doc 02 has a State Model section, extraction should find it."""
        if 2 not in enforcer.docs:
            pytest.skip("Doc 02 not loaded")
        result = enforcer.get_doc_section(2, "state_model")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# CLI integration (smoke test)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_new_command_creates_project_relaxed(self, tmp_path):
        """Smoke test: create a project via CLI logic with --relaxed."""
        vision_file = tmp_path / "test_vision.md"
        vision_file.write_text("# My Test Sim\n\n## Identity\n- Purpose: Testing\n")

        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "new", "--vision", str(vision_file), "--relaxed",
        ])
        assert result == 0

        projects_dir = tmp_path / "projects"
        ids = ProjectState.list_projects(projects_dir)
        assert len(ids) == 1

    def test_new_command_strict_rejects_incomplete(self, tmp_path):
        """Strict mode (default) rejects vision missing required fields."""
        vision_file = tmp_path / "incomplete.md"
        vision_file.write_text("# Just A Title\n\nSome text.\n")

        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "new", "--vision", str(vision_file),
        ])
        assert result == 1  # Should fail

    def test_new_command_strict_accepts_complete(self, tmp_path):
        """Strict mode accepts a complete vision contract."""
        from tests.test_project_state import SAMPLE_VISION_MD
        vision_file = tmp_path / "complete.md"
        vision_file.write_text(SAMPLE_VISION_MD)

        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "new", "--vision", str(vision_file),
        ])
        assert result == 0

    def test_status_command_shows_project(self, tmp_path):
        """Create a project then check status."""
        vision_file = tmp_path / "vision.md"
        vision_file.write_text("# Status Test\n\n## Identity\n- Purpose: Testing\n")

        from cli.main import main
        main([
            "--projects-dir", str(tmp_path / "projects"),
            "new", "--vision", str(vision_file), "--relaxed",
        ])

        ids = ProjectState.list_projects(tmp_path / "projects")
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "status", "--project", ids[0],
        ])
        assert result == 0

    def test_status_lists_all_projects(self, tmp_path):
        """Status without --project lists all."""
        for name in ["alpha", "beta"]:
            vision_file = tmp_path / f"{name}.md"
            vision_file.write_text(f"# {name.title()}\n")
            from cli.main import main
            main([
                "--projects-dir", str(tmp_path / "projects"),
                "new", "--vision", str(vision_file), "--relaxed",
            ])

        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "status",
        ])
        assert result == 0

    def test_status_nonexistent_project_returns_error(self, tmp_path):
        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_path / "projects"),
            "status", "--project", "nonexistent",
        ])
        assert result == 1
