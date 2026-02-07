"""Tier 2 tests — Architect Session, Gate Manager, Journal, CLI commands.

Tests use a mock connector (no real AI calls). Covers:
- GateManager: create, respond, list, build_response_message
- Journal: format, append, load, recent
- ArchitectSession: create_session, vision_intake, system_design, persistence
- CLI: architect, approve, reject, gates commands
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from orchestration.architect import (
    ArchitectSession,
    _extract_questions,
    _parse_gate_options,
    _find_recommended,
    save_session_messages,
    load_session_messages,
    _serialize_history,
)
from orchestration.constitution import ConstitutionEnforcer
from orchestration.gate_manager import GateManager
from orchestration.journal import (
    append_entry,
    format_entry,
    journal_path_for_project,
    load_entries,
    load_recent_entries,
)
from orchestration.models import (
    Gate,
    GateOption,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
    Phase,
    VisionContract,
)
from orchestration.project_state import ProjectState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_projects(tmp_path):
    """Create a temporary projects directory."""
    d = tmp_path / "projects"
    d.mkdir()
    return d


@pytest.fixture
def docs_dir():
    """Path to constitutional docs."""
    return Path("constitutional_docs")


@pytest.fixture
def sample_project(tmp_projects):
    """Create a minimal project for testing."""
    vision = VisionContract(
        project_name="Test Project",
        purpose="Testing Tier 2",
        raw_markdown="# Test Project\n\n## Identity\n- Purpose: Testing Tier 2",
    )
    project = ProjectState(
        project_name="Test Project",
        vision_contract=vision,
        current_tier=1,
        current_phase="vision_intake",
    )
    project.save(tmp_projects)
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
    """Mock NexusConnector that satisfies ConnectorProtocol."""
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
    """Return a factory function that creates MockConnectors with preset responses."""
    def factory(provider="mock", model="mock", system_prompt="", **kwargs):
        return MockConnector(_responses=responses or [])
    return factory


# ---------------------------------------------------------------------------
# Journal tests
# ---------------------------------------------------------------------------

class TestJournal:
    def test_format_entry_has_all_sections(self):
        entry = format_entry(
            phase="vision_intake",
            tier=1,
            context="Reviewed vision.",
            reasoning="Need clarity.",
        )
        assert "JOURNAL ENTRY" in entry
        assert "Phase:      vision_intake" in entry
        assert "Tier:       1" in entry
        assert "Reviewed vision." in entry
        assert "Need clarity." in entry

    def test_format_entry_custom_fields(self):
        entry = format_entry(
            phase="system_design",
            tier=2,
            context="Designing system.",
            reasoning="Multiple options explored.",
            options_explored="Option A, Option B",
            open_questions="How to handle caching?",
            concerns="Timeline risk.",
            notes="Resume from here.",
        )
        assert "Option A, Option B" in entry
        assert "How to handle caching?" in entry
        assert "Timeline risk." in entry
        assert "Resume from here." in entry

    def test_append_and_load(self, tmp_path):
        jpath = tmp_path / "journal.md"
        entry1 = format_entry("phase1", 1, "ctx1", "reason1")
        entry2 = format_entry("phase2", 2, "ctx2", "reason2")

        append_entry(jpath, entry1)
        entries = load_entries(jpath)
        assert len(entries) == 1

        append_entry(jpath, entry2)
        entries = load_entries(jpath)
        assert len(entries) == 2
        assert "ctx1" in entries[0]
        assert "ctx2" in entries[1]

    def test_load_recent_entries(self, tmp_path):
        jpath = tmp_path / "journal.md"
        for i in range(5):
            append_entry(jpath, format_entry(f"phase{i}", i, f"ctx{i}", f"reason{i}"))

        recent = load_recent_entries(jpath, count=2)
        assert len(recent) == 2
        assert "ctx3" in recent[0]
        assert "ctx4" in recent[1]

    def test_load_entries_empty_file(self, tmp_path):
        jpath = tmp_path / "journal.md"
        assert load_entries(jpath) == []

    def test_journal_path_for_project(self, tmp_path):
        path = journal_path_for_project("proj_abc", tmp_path)
        assert path == tmp_path / "proj_abc" / "architect_journal.md"


# ---------------------------------------------------------------------------
# GateManager tests
# ---------------------------------------------------------------------------

class TestGateManager:
    def test_create_gate(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.VISION_CONFIRMED,
            summary="Test gate",
            architect_raw_response="Response text",
            questions=["Q1?", "Q2?"],
        )

        assert gate.gate_id.startswith("gate_")
        assert gate.gate_type == "vision_confirmed"
        assert gate.status == "pending"
        assert gate.summary == "Test gate"
        assert gate.questions == ["Q1?", "Q2?"]
        assert sample_project.pending_gate is gate
        assert len(sample_project.blocked_on) == 1

    def test_create_gate_with_options(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        options = [
            GateOption(letter="A", name="Option A", is_recommended=True),
            GateOption(letter="B", name="Option B"),
        ]
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Design gate",
            options=options,
            recommended_option="A",
        )

        assert len(gate.options) == 2
        assert gate.recommended_option == "A"
        assert gate.options[0]["letter"] == "A"
        assert gate.options[0]["is_recommended"] is True

    def test_respond_choose(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Choose one",
        )

        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="B",
        )
        updated = gm.respond_to_gate(sample_project, gate.gate_id, response)

        assert updated.status == "approved"
        assert updated.human_response["chosen_option"] == "B"
        assert sample_project.pending_gate is None
        assert sample_project.blocked_on == []

    def test_respond_choose_with_modifications(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Choose one",
        )

        response = GateResponse(
            response_type=GateResponseType.CHOOSE_WITH_MODIFICATIONS.value,
            chosen_option="A",
            modifications="Use Redis instead of Memcached",
        )
        updated = gm.respond_to_gate(sample_project, gate.gate_id, response)

        assert updated.status == "approved"
        assert updated.conditions == ["Use Redis instead of Memcached"]

    def test_respond_revise(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Choose one",
        )

        response = GateResponse(
            response_type=GateResponseType.REVISE_AND_PROCEED.value,
            revision_feedback="Fix the caching layer",
        )
        updated = gm.respond_to_gate(sample_project, gate.gate_id, response)

        assert updated.status == "approved"
        assert updated.conditions == ["Fix the caching layer"]

    def test_respond_reject(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Choose one",
        )

        response = GateResponse(
            response_type=GateResponseType.REJECT.value,
            rejection_reason="Completely wrong direction",
        )
        updated = gm.respond_to_gate(sample_project, gate.gate_id, response)

        assert updated.status == "rejected"

    def test_respond_to_non_pending_raises(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            project=sample_project,
            gate_type=GateType.VISION_CONFIRMED,
            summary="Test",
        )

        # Respond once
        response = GateResponse(response_type=GateResponseType.CHOOSE.value, chosen_option="A")
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        # Respond again — should fail
        # Recreate pending_gate to simulate stale state
        sample_project.pending_gate = gate  # but gate.status is now "approved"
        with pytest.raises(ValueError, match="not pending"):
            gm.respond_to_gate(sample_project, gate.gate_id, response)

    def test_list_gates(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Gate 1")
        # Clear pending so we can create another
        sample_project.pending_gate = None
        gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Gate 2")

        gates = gm.list_gates(sample_project.project_id)
        assert len(gates) == 2
        types = {g.gate_type for g in gates}
        assert "vision_confirmed" in types
        assert "system_design" in types

    def test_gate_persists_to_disk(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            sample_project, GateType.VISION_CONFIRMED, "Persist test"
        )

        # Load from disk
        loaded = gm._load_gate(sample_project.project_id, gate.gate_id)
        assert loaded.gate_id == gate.gate_id
        assert loaded.summary == "Persist test"

    def test_build_response_message_choose(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Choose")
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="B",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        msg = gm.build_response_message(gate)
        assert "Option B" in msg
        assert "Proceed" in msg

    def test_build_response_message_combine(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Choose")
        response = GateResponse(
            response_type=GateResponseType.COMBINE.value,
            combine_instructions="Take A's backend with B's frontend",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        msg = gm.build_response_message(gate)
        assert "combine" in msg.lower()
        assert "A's backend with B's frontend" in msg

    def test_build_response_message_explore_differently(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Choose")
        response = GateResponse(
            response_type=GateResponseType.EXPLORE_DIFFERENTLY.value,
            redirect_instructions="Consider a microservices approach",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        msg = gm.build_response_message(gate)
        assert "microservices" in msg

    def test_build_response_message_reject(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Choose")
        response = GateResponse(
            response_type=GateResponseType.REJECT.value,
            rejection_reason="Wrong approach entirely",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        msg = gm.build_response_message(gate)
        assert "Wrong approach" in msg
        assert "reject" in msg.lower() or "Rejecting" in msg

    def test_build_response_message_no_response(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Pending")
        # No response yet
        msg = gm.build_response_message(gate)
        assert msg == ""

    def test_find_gate_not_found_raises(self, tmp_projects, sample_project):
        gm = GateManager(tmp_projects)
        with pytest.raises(ValueError, match="not found"):
            gm._find_gate(sample_project, "gate_nonexistent")


# ---------------------------------------------------------------------------
# Architect session tests (mocked connector)
# ---------------------------------------------------------------------------

class TestArchitectSession:
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

    def test_create_session(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        connector = session.create_session()

        assert connector is not None
        assert session.connector is connector
        assert connector.session_id == "mock_session_001"

    def test_vision_intake_creates_gate(self, sample_project, tmp_projects, docs_dir):
        vision_response = (
            "## My Understanding\n"
            "This is a test project for Tier 2.\n\n"
            "## Clarifying Questions\n"
            "- What is the target deployment environment?\n"
            "- How many concurrent users should the system support?\n"
            "- What authentication method should be used?\n"
        )
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[vision_response],
        )

        gate = asyncio.run(session.run_vision_intake())

        assert gate.gate_type == "vision_confirmed"
        assert gate.status == "pending"
        assert len(gate.questions) >= 2
        assert sample_project.pending_gate is gate

    def test_vision_intake_saves_session(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Questions: What is X?"],
        )

        asyncio.run(session.run_vision_intake())

        # Verify session was persisted
        sid, messages = load_session_messages(sample_project.project_id, tmp_projects)
        assert len(messages) > 0

    def test_vision_intake_appends_journal(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Some response"],
        )

        asyncio.run(session.run_vision_intake())

        jpath = journal_path_for_project(sample_project.project_id, tmp_projects)
        entries = load_entries(jpath)
        assert len(entries) == 1
        assert "Vision Contract" in entries[0]

    def test_process_vision_response_advances_phase(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["Vision questions here", "Acknowledged, proceeding."],
        )

        gate = asyncio.run(session.run_vision_intake())

        # Simulate human responding
        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        asyncio.run(session.process_vision_response(gate))

        assert sample_project.current_phase == "system_design"

    def test_system_design_creates_gate_with_options(self, sample_project, tmp_projects, docs_dir):
        design_response = (
            'OPTION A: "Monolithic Architecture"\n\n'
            "  Summary:\n"
            "    Single deployable unit.\n\n"
            "  Key characteristics:\n"
            "    - Simple deployment\n"
            "    - Shared database\n\n"
            "  Tradeoffs:\n"
            "    Optimizes for: Simplicity\n"
            "    Costs:         Scalability\n\n"
            "  Consequence chain:\n"
            "    1st order:  Fast initial development\n"
            "    2nd order:  Growing pains at scale\n"
            "    3rd order:  Eventual rewrite needed\n\n"
            "  Build impact:\n"
            "    Subsystems:     3\n"
            "    Builder tasks:  8\n"
            "    Estimated cost: $50-100\n"
            "    Timeline:       2 weeks\n\n"
            "  Risk:\n"
            "    Scaling bottlenecks\n\n"
            'OPTION B: "Microservices" ★ RECOMMENDED\n\n'
            "  Summary:\n"
            "    Distributed services.\n\n"
            "  Key characteristics:\n"
            "    - Independent scaling\n"
            "    - Service isolation\n\n"
            "  Tradeoffs:\n"
            "    Optimizes for: Scalability\n"
            "    Costs:         Complexity\n\n"
            "  Consequence chain:\n"
            "    1st order:  More initial setup\n"
            "    2nd order:  Better long-term maintainability\n"
            "    3rd order:  Easier team scaling\n\n"
            "  Build impact:\n"
            "    Subsystems:     6\n"
            "    Builder tasks:  15\n"
            "    Estimated cost: $200-400\n"
            "    Timeline:       4 weeks\n\n"
            "  Risk:\n"
            "    Distributed system complexity\n"
        )
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[design_response],
        )
        sample_project.current_phase = "system_design"

        gate = asyncio.run(session.run_system_design())

        assert gate.gate_type == "system_design"
        assert gate.status == "pending"
        assert len(gate.options) == 2
        assert gate.recommended_option == "B"

    def test_process_design_response_stores_template(self, sample_project, tmp_projects, docs_dir):
        design_options = 'OPTION A: "Simple"\n\nSummary:\n  A simple system.\n'
        detailed_design = "# Architecture Template\n\n## Subsystems\n- Auth\n- API\n- DB"

        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[design_options, detailed_design],
        )
        sample_project.current_phase = "system_design"

        gate = asyncio.run(session.run_system_design())

        # Respond to gate
        gm = GateManager(tmp_projects)
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)

        content = asyncio.run(session.process_design_response(gate))

        assert "Architecture Template" in content or content  # some content returned
        assert sample_project.current_phase == "detailed_design"
        assert sample_project.architecture_template != ""

    def test_session_persistence_roundtrip(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=["test response"],
        )

        asyncio.run(session.run_vision_intake())

        # Save was called inside run_vision_intake
        sid, messages = load_session_messages(sample_project.project_id, tmp_projects)
        assert len(messages) >= 2  # at least user + assistant

        # Save manually too
        save_session_messages(
            sample_project.project_id, tmp_projects,
            messages=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
            session_id="test_session",
        )
        sid2, msgs2 = load_session_messages(sample_project.project_id, tmp_projects)
        assert sid2 == "test_session"
        assert len(msgs2) == 2

    def test_resume_session_replays_history(self, sample_project, tmp_projects, docs_dir):
        # Save some history
        save_session_messages(
            sample_project.project_id, tmp_projects,
            messages=[
                {"role": "user", "content": "vision here"},
                {"role": "assistant", "content": "questions here"},
            ],
            session_id="old_session",
        )

        session = self._make_session(sample_project, tmp_projects, docs_dir)
        connector = session.resume_session()

        # History should have the replayed messages
        assert len(connector.conversation_history) == 2


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------

class TestParsing:
    def test_extract_questions(self):
        text = (
            "## Questions\n"
            "- What deployment platform will be used?\n"
            "- How many concurrent users are expected?\n"
            "Some non-question text here.\n"
            "- Short?\n"  # Too short, should be skipped
        )
        questions = _extract_questions(text)
        assert len(questions) == 2
        assert "deployment platform" in questions[0]
        assert "concurrent users" in questions[1]

    def test_extract_questions_numbered(self):
        text = (
            "1. What database engine should be used?\n"
            "2. Is there an existing auth system to integrate with?\n"
        )
        questions = _extract_questions(text)
        assert len(questions) == 2

    def test_parse_gate_options_two_options(self):
        text = (
            'OPTION A: "Monolithic"\n\n'
            "  Summary:\n"
            "    Single deployable unit.\n\n"
            'OPTION B: "Microservices"\n\n'
            "  Summary:\n"
            "    Distributed services.\n"
        )
        options = _parse_gate_options(text)
        assert len(options) == 2
        assert options[0].letter == "A"
        assert options[0].name == "Monolithic"
        assert options[1].letter == "B"
        assert options[1].name == "Microservices"

    def test_parse_gate_options_recommended(self):
        text = (
            'OPTION A: "Simple"\n\n'
            "  Summary: Basic.\n\n"
            'OPTION B: "Complex" ★ RECOMMENDED\n\n'
            "  Summary: Advanced.\n"
        )
        options = _parse_gate_options(text)
        assert options[0].is_recommended is False
        assert options[1].is_recommended is True

    def test_find_recommended_from_options(self):
        text = 'OPTION A: "Foo"\nOPTION B: "Bar" ★ RECOMMENDED\n'
        options = _parse_gate_options(text)
        rec = _find_recommended(text, options)
        assert rec == "B"

    def test_find_recommended_fallback(self):
        text = "I recommend Option C for this project."
        rec = _find_recommended(text, [])
        assert rec == "C"

    def test_parse_option_fields(self):
        text = (
            'OPTION A: "Full Stack"\n\n'
            "  Summary:\n"
            "    A full stack solution.\n\n"
            "  Key characteristics:\n"
            "    - React frontend\n"
            "    - Node backend\n\n"
            "  Tradeoffs:\n"
            "    Optimizes for: Developer velocity\n"
            "    Costs:         Learning curve\n\n"
            "  Consequence chain:\n"
            "    1st order:  Fast prototyping\n"
            "    2nd order:  Technical debt\n"
            "    3rd order:  Refactor needed\n\n"
            "  Build impact:\n"
            "    Subsystems:     4\n"
            "    Builder tasks:  12\n"
            "    Estimated cost: $100-200\n"
            "    Timeline:       3 weeks\n\n"
            "  Risk:\n"
            "    Scope creep\n"
        )
        options = _parse_gate_options(text)
        assert len(options) == 1
        opt = options[0]
        assert opt.name == "Full Stack"
        assert "full stack" in opt.summary.lower()
        assert opt.optimizes_for == "Developer velocity"
        assert opt.costs == "Learning curve"
        assert opt.consequence_1st == "Fast prototyping"
        assert opt.subsystems == 4
        assert "Scope creep" in opt.risk

    def test_parse_empty_text(self):
        assert _parse_gate_options("") == []
        assert _extract_questions("") == []


# ---------------------------------------------------------------------------
# Gate model tests
# ---------------------------------------------------------------------------

class TestGateModels:
    def test_gate_option_roundtrip(self):
        opt = GateOption(
            letter="A",
            name="Test",
            summary="A test option",
            key_characteristics=["fast", "simple"],
            is_recommended=True,
        )
        d = opt.to_dict()
        loaded = GateOption.from_dict(d)
        assert loaded.letter == "A"
        assert loaded.name == "Test"
        assert loaded.is_recommended is True
        assert loaded.key_characteristics == ["fast", "simple"]

    def test_gate_response_roundtrip(self):
        resp = GateResponse(
            response_type=GateResponseType.CHOOSE_WITH_MODIFICATIONS.value,
            chosen_option="B",
            modifications="Use PostgreSQL instead",
        )
        d = resp.to_dict()
        loaded = GateResponse.from_dict(d)
        assert loaded.response_type == "choose_with_modifications"
        assert loaded.chosen_option == "B"
        assert loaded.modifications == "Use PostgreSQL instead"

    def test_gate_roundtrip_with_options(self):
        gate = Gate(
            gate_id="gate_test123",
            gate_type="system_design",
            phase="system_design",
            status="pending",
            summary="Choose architecture",
            options=[
                GateOption(letter="A", name="Mono").to_dict(),
                GateOption(letter="B", name="Micro").to_dict(),
            ],
            recommended_option="B",
        )
        d = gate.to_dict()
        loaded = Gate.from_dict(d)
        assert loaded.gate_id == "gate_test123"
        assert len(loaded.options) == 2
        assert loaded.recommended_option == "B"

    def test_gate_response_types_enum(self):
        assert GateResponseType.CHOOSE.value == "choose"
        assert GateResponseType.COMBINE.value == "combine"
        assert GateResponseType.REJECT.value == "reject"
        assert len(GateResponseType) == 6


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------

class TestCLIGates:
    def test_gates_command_empty(self, tmp_projects, sample_project, capsys):
        from cli.main import main
        result = main([
            "--projects-dir", str(tmp_projects),
            "gates", "--project", sample_project.project_id,
        ])
        assert result == 0
        assert "No gates found" in capsys.readouterr().out

    def test_gates_command_lists_gates(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        # Create a gate first
        gm = GateManager(tmp_projects)
        gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Vision gate")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "gates", "--project", sample_project.project_id,
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "vision_confirmed" in out
        assert "PENDING" in out


class TestCLIApprove:
    def test_approve_choose(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Choose")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", sample_project.project_id,
            "--gate", gate.gate_id,
            "--choice", "A",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "approved" in out.lower()

    def test_approve_revise(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Design")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", sample_project.project_id,
            "--gate", gate.gate_id,
            "--revise", "Fix the caching layer",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "approved" in out.lower()

    def test_approve_combine(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Design")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", sample_project.project_id,
            "--gate", gate.gate_id,
            "--combine", "A's backend + B's frontend",
        ])
        assert result == 0

    def test_approve_no_args_fails(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Choose")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", sample_project.project_id,
            "--gate", gate.gate_id,
        ])
        assert result == 1
        err = capsys.readouterr().err
        assert "Must specify" in err

    def test_approve_nonexistent_project(self, tmp_projects, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", "nonexistent",
            "--gate", "gate_xxx",
            "--choice", "A",
        ])
        assert result == 1

    def test_approve_nonexistent_gate(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "approve",
            "--project", sample_project.project_id,
            "--gate", "gate_nonexistent",
            "--choice", "A",
        ])
        assert result == 1


class TestCLIReject:
    def test_reject(self, tmp_projects, sample_project, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(sample_project, GateType.SYSTEM_DESIGN, "Design")
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "reject",
            "--project", sample_project.project_id,
            "--gate", gate.gate_id,
            "--feedback", "Wrong direction entirely",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "REJECTED" in out
        assert "Wrong direction" in out

    def test_reject_nonexistent_project(self, tmp_projects, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "reject",
            "--project", "nonexistent",
            "--gate", "gate_xxx",
            "--feedback", "nope",
        ])
        assert result == 1


class TestCLIArchitect:
    def test_architect_blocked_on_gate(self, tmp_projects, sample_project, docs_dir, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gm.create_gate(sample_project, GateType.VISION_CONFIRMED, "Pending gate")
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

    def test_architect_nonexistent_project(self, tmp_projects, docs_dir, capsys):
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", "nonexistent",
        ])
        assert result == 1


# ---------------------------------------------------------------------------
# Integration: full gate lifecycle
# ---------------------------------------------------------------------------

class TestGateLifecycle:
    def test_full_lifecycle(self, tmp_projects, sample_project):
        """Create gate → respond → verify state cleared → build response message."""
        gm = GateManager(tmp_projects)

        # Create
        gate = gm.create_gate(
            sample_project, GateType.SYSTEM_DESIGN, "Pick one",
            options=[
                GateOption(letter="A", name="Simple"),
                GateOption(letter="B", name="Complex", is_recommended=True),
            ],
            recommended_option="B",
        )
        assert sample_project.pending_gate is gate
        assert len(sample_project.blocked_on) == 1

        # Respond
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="B",
        )
        updated = gm.respond_to_gate(sample_project, gate.gate_id, response)

        assert updated.status == "approved"
        assert sample_project.pending_gate is None
        assert sample_project.blocked_on == []

        # Build message for Architect
        msg = gm.build_response_message(updated)
        assert "Option B" in msg

        # Verify persistence
        loaded = gm._load_gate(sample_project.project_id, gate.gate_id)
        assert loaded.status == "approved"
        assert loaded.human_response is not None
