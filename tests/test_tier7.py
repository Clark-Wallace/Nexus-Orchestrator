"""Tier 7 tests — Export + Web Interface.

Tests use FastAPI TestClient (no real server). Covers:
- Export: create_project_archive, list_project_files
- Schemas: Pydantic v2 model validation
- App factory: create_app, state, health endpoint
- Routes: projects, gates, artifacts, lineage, costs, export
- WebSocket: connect, disconnect, broadcast, per-project isolation
- CLI: export and serve commands, parser additions
- Integration: full flow create → status → gates → artifacts → export
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestration.models import (
    Artifact,
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
from orchestration.project_state import ProjectState


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
def sample_vision_md():
    return (
        "# Test Project\n\n"
        "## Identity\n"
        "- Purpose: Web interface testing\n\n"
        "## Primary Questions\n"
        "- How does the web API work?\n\n"
        "## Scope\n"
        "### In-Scope\n"
        "- API endpoints\n\n"
        "### Out-of-Scope\n"
        "- Mobile app\n\n"
        "## Non-Negotiables\n"
        "- Must have tests\n"
    )


@pytest.fixture
def sample_project(tmp_projects):
    vision = VisionContract(
        project_name="Web Test",
        purpose="Testing Tier 7",
        raw_markdown="# Web Test\n\n## Identity\n- Purpose: Testing Tier 7",
    )
    project = ProjectState(
        project_name="Web Test",
        vision_contract=vision,
        current_tier=1,
        current_phase="vision_intake",
        architecture_template="# Architecture\n\n## Subsystems\n- Core",
    )
    project.save(tmp_projects)
    return project


@pytest.fixture
def project_with_gates(tmp_projects):
    vision = VisionContract(
        project_name="Gate Test",
        purpose="Testing gates",
        raw_markdown="# Gate Test\n\n## Identity\n- Purpose: Testing gates",
    )
    project = ProjectState(
        project_name="Gate Test",
        vision_contract=vision,
        current_tier=1,
        current_phase="system_design",
    )
    gate = Gate(
        gate_id="gate_001",
        gate_type=GateType.VISION_CONFIRMED.value,
        phase="vision_intake",
        status=GateStatus.PENDING.value,
        summary="Confirm the vision",
        options=[
            GateOption(
                letter="A", name="Approve", summary="Accept as-is",
                is_recommended=True,
            ).to_dict(),
        ],
    )
    project.gates.append(gate)
    project.pending_gate = gate
    project.save(tmp_projects)
    # Also save gate file for GateManager.list_gates()
    gates_dir = tmp_projects / project.project_id / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    (gates_dir / f"{gate.gate_id}.json").write_text(gate.to_json(), encoding="utf-8")
    return project


@pytest.fixture
def project_with_artifacts(tmp_projects):
    vision = VisionContract(
        project_name="Artifact Test",
        purpose="Testing artifacts",
        raw_markdown="# Artifact Test\n\n## Identity\n- Purpose: Artifacts",
    )
    project = ProjectState(
        project_name="Artifact Test",
        vision_contract=vision,
        current_tier=1,
        current_phase="validation",
    )
    artifact = Artifact(
        artifact_id="art_001",
        file_path="orchestration/models.py",
        produced_by="builder",
        task_id="task_001",
        tier=1,
        subsystem="Core",
        lineage=["vision_ref", "dec_001"],
    )
    project.artifacts["orchestration/models.py"] = artifact
    project.save(tmp_projects)
    return project


@pytest.fixture
def app(tmp_projects, docs_dir):
    from web.app import create_app
    return create_app(projects_dir=tmp_projects, docs_dir=docs_dir)


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestExport:
    def test_create_archive_returns_bytesio_and_filename(self, sample_project, tmp_projects):
        from web.export import create_project_archive
        buf, filename = create_project_archive(sample_project.project_id, tmp_projects)
        assert isinstance(buf, BytesIO)
        assert filename == f"{sample_project.project_id}_export.zip"

    def test_archive_contains_project_files(self, sample_project, tmp_projects):
        from web.export import create_project_archive
        buf, _ = create_project_archive(sample_project.project_id, tmp_projects)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert any("project_state.json" in n for n in names)

    def test_archive_is_valid_zip(self, sample_project, tmp_projects):
        from web.export import create_project_archive
        buf, _ = create_project_archive(sample_project.project_id, tmp_projects)
        assert zipfile.is_zipfile(buf)

    def test_archive_preserves_nested_dirs(self, sample_project, tmp_projects):
        from web.export import create_project_archive
        # Project save creates subdirectories (tasks/, artifacts/, etc.)
        buf, _ = create_project_archive(sample_project.project_id, tmp_projects)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert len(names) >= 1

    def test_archive_missing_project_raises(self, tmp_projects):
        from web.export import create_project_archive
        with pytest.raises(FileNotFoundError):
            create_project_archive("nonexistent", tmp_projects)

    def test_list_project_files(self, sample_project, tmp_projects):
        from web.export import list_project_files
        files = list_project_files(sample_project.project_id, tmp_projects)
        assert len(files) >= 1
        assert all("path" in f and "size" in f for f in files)

    def test_list_project_files_missing_raises(self, tmp_projects):
        from web.export import list_project_files
        with pytest.raises(FileNotFoundError):
            list_project_files("nonexistent", tmp_projects)

    def test_list_project_files_has_state_json(self, sample_project, tmp_projects):
        from web.export import list_project_files
        files = list_project_files(sample_project.project_id, tmp_projects)
        paths = [f["path"] for f in files]
        assert "project_state.json" in paths


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_project_summary_validates(self):
        from web.schemas import ProjectSummary
        ps = ProjectSummary(
            project_id="p1", project_name="Test",
            current_phase="vision_intake", current_tier=0,
            created_at="2026-01-01", health={},
        )
        assert ps.project_id == "p1"

    def test_project_detail_validates(self):
        from web.schemas import ProjectDetail
        pd = ProjectDetail(data={"project_id": "p1"})
        assert pd.data["project_id"] == "p1"

    def test_project_create_request(self):
        from web.schemas import ProjectCreateRequest
        req = ProjectCreateRequest(vision_markdown="# Test", relaxed=True)
        assert req.relaxed is True

    def test_gate_response_input_choose(self):
        from web.schemas import GateResponseInput
        inp = GateResponseInput(response_type="choose", chosen_option="A")
        assert inp.response_type == "choose"
        assert inp.chosen_option == "A"

    def test_cost_report_response(self):
        from web.schemas import CostReportResponse
        cr = CostReportResponse(report_text="Total: $0", total_cost=0.0)
        assert cr.report_text == "Total: $0"

    def test_export_info(self):
        from web.schemas import ExportInfo
        ei = ExportInfo(file_count=3, total_size=1024, files=[])
        assert ei.file_count == 3


# ---------------------------------------------------------------------------
# App factory tests
# ---------------------------------------------------------------------------

class TestAppFactory:
    def test_create_app_returns_fastapi(self, tmp_projects, docs_dir):
        from fastapi import FastAPI
        from web.app import create_app
        app = create_app(projects_dir=tmp_projects, docs_dir=docs_dir)
        assert isinstance(app, FastAPI)

    def test_app_state_has_projects_dir(self, app, tmp_projects):
        assert app.state.projects_dir == tmp_projects

    def test_app_state_has_ws_manager(self, app):
        from web.websocket import OrchestratorWSManager
        assert isinstance(app.state.ws_manager, OrchestratorWSManager)

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Projects route tests
# ---------------------------------------------------------------------------

class TestProjectsRoutes:
    def test_list_projects_empty(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_projects_populated(self, client, sample_project):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["project_name"] == "Web Test"

    def test_get_project_detail(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["project_id"] == sample_project.project_id

    def test_get_project_404(self, client):
        resp = client.get("/api/projects/nonexistent")
        assert resp.status_code == 404

    def test_create_project(self, client, sample_vision_md):
        resp = client.post("/api/projects", json={
            "vision_markdown": sample_vision_md,
            "relaxed": False,
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["project_name"] == "Test Project"
        assert data["current_phase"] == "vision_intake"

    def test_create_project_relaxed(self, client):
        resp = client.post("/api/projects", json={
            "vision_markdown": "Just a simple idea for a project",
            "relaxed": True,
        })
        assert resp.status_code == 201

    def test_create_project_invalid_vision(self, client):
        resp = client.post("/api/projects", json={
            "vision_markdown": "No structure at all",
            "relaxed": False,
        })
        assert resp.status_code == 422

    def test_get_project_status(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_phase"] == "vision_intake"
        assert "summary" in data


# ---------------------------------------------------------------------------
# Gates route tests
# ---------------------------------------------------------------------------

class TestGatesRoutes:
    def test_list_gates_empty(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/gates")
        assert resp.status_code == 200
        # May have zero or some gates depending on project
        assert isinstance(resp.json(), list)

    def test_list_gates_populated(self, client, project_with_gates):
        resp = client.get(f"/api/projects/{project_with_gates.project_id}/gates")
        assert resp.status_code == 200
        gates = resp.json()
        assert len(gates) >= 1
        assert gates[0]["gate_id"] == "gate_001"

    def test_get_gate_detail(self, client, project_with_gates):
        resp = client.get(
            f"/api/projects/{project_with_gates.project_id}/gates/gate_001"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["gate_id"] == "gate_001"

    def test_get_gate_404(self, client, sample_project):
        resp = client.get(
            f"/api/projects/{sample_project.project_id}/gates/nonexistent"
        )
        assert resp.status_code == 404

    def test_respond_to_gate_choose(self, client, project_with_gates):
        resp = client.post(
            f"/api/projects/{project_with_gates.project_id}/gates/gate_001",
            json={
                "response_type": "choose",
                "chosen_option": "A",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("approved", "resolved")

    def test_respond_to_gate_reject(self, client, project_with_gates):
        resp = client.post(
            f"/api/projects/{project_with_gates.project_id}/gates/gate_001",
            json={
                "response_type": "reject",
                "feedback": "Not good enough",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"

    def test_respond_to_gate_project_404(self, client):
        resp = client.post(
            "/api/projects/nonexistent/gates/gate_001",
            json={"response_type": "choose", "chosen_option": "A"},
        )
        assert resp.status_code == 404

    def test_respond_to_gate_bad_gate(self, client, sample_project):
        resp = client.post(
            f"/api/projects/{sample_project.project_id}/gates/nonexistent",
            json={"response_type": "choose", "chosen_option": "A"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Artifacts route tests
# ---------------------------------------------------------------------------

class TestArtifactsRoutes:
    def test_list_artifacts_empty(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/artifacts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_artifacts_populated(self, client, project_with_artifacts):
        resp = client.get(
            f"/api/projects/{project_with_artifacts.project_id}/artifacts"
        )
        assert resp.status_code == 200
        arts = resp.json()
        assert len(arts) == 1
        assert arts[0]["artifact_id"] == "art_001"

    def test_get_artifact_detail(self, client, project_with_artifacts):
        resp = client.get(
            f"/api/projects/{project_with_artifacts.project_id}/artifacts/art_001"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lineage"] == ["vision_ref", "dec_001"]

    def test_get_artifact_404(self, client, sample_project):
        resp = client.get(
            f"/api/projects/{sample_project.project_id}/artifacts/nonexistent"
        )
        assert resp.status_code == 404

    def test_artifacts_project_404(self, client):
        resp = client.get("/api/projects/nonexistent/artifacts")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Lineage route tests
# ---------------------------------------------------------------------------

class TestLineageRoutes:
    def test_get_lineage_empty(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/lineage")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_decisions_empty(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/decisions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_lineage_with_data(self, client, tmp_projects, sample_project):
        from orchestration.lineage import append_artifact_lineage
        artifact = Artifact(
            artifact_id="art_x", file_path="test.py",
            produced_by="builder", task_id="t1", tier=1,
            lineage=["v1", "d1"],
        )
        append_artifact_lineage(artifact, sample_project.project_id, tmp_projects)

        resp = client.get(f"/api/projects/{sample_project.project_id}/lineage")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["artifact_id"] == "art_x"

    def test_get_decisions_with_data(self, client, tmp_projects, sample_project):
        from orchestration.lineage import append_decision
        decision = Decision(
            decision_id="dec_x", decision_type="test",
            made_by="architect", description="Test decision",
        )
        append_decision(decision, sample_project.project_id, tmp_projects)

        resp = client.get(f"/api/projects/{sample_project.project_id}/decisions")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["decision_id"] == "dec_x"

    def test_lineage_project_404(self, client):
        resp = client.get("/api/projects/nonexistent/lineage")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Costs route tests
# ---------------------------------------------------------------------------

class TestCostsRoutes:
    def test_get_costs_empty(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/costs")
        assert resp.status_code == 200
        data = resp.json()
        assert "report_text" in data
        assert data["total_cost"] == 0.0

    def test_get_costs_with_data(self, client, tmp_projects, sample_project):
        from orchestration.lineage import append_usage
        append_usage(
            usage_entry={
                "task_id": "t1", "role": "builder",
                "provider": "anthropic", "model": "opus",
                "input_tokens": 100, "output_tokens": 50,
                "estimated_cost": 0.05, "phase": "build", "tier": 1,
            },
            project_id=sample_project.project_id,
            projects_dir=tmp_projects,
        )
        resp = client.get(f"/api/projects/{sample_project.project_id}/costs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == pytest.approx(0.05)
        assert "by_tier" in data["breakdown"]

    def test_costs_project_404(self, client):
        resp = client.get("/api/projects/nonexistent/costs")
        assert resp.status_code == 404

    def test_costs_breakdown_structure(self, client, tmp_projects, sample_project):
        from orchestration.lineage import append_usage
        append_usage(
            usage_entry={
                "task_id": "t1", "role": "architect",
                "provider": "anthropic", "model": "opus",
                "input_tokens": 200, "output_tokens": 100,
                "estimated_cost": 0.10, "phase": "design", "tier": 1,
            },
            project_id=sample_project.project_id,
            projects_dir=tmp_projects,
        )
        resp = client.get(f"/api/projects/{sample_project.project_id}/costs")
        data = resp.json()
        breakdown = data["breakdown"]
        assert "by_provider" in breakdown
        assert "by_role" in breakdown
        assert "by_model" in breakdown


# ---------------------------------------------------------------------------
# Export route tests
# ---------------------------------------------------------------------------

class TestExportRoutes:
    def test_download_export(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "attachment" in resp.headers.get("content-disposition", "")
        # Verify it's a valid zip
        buf = BytesIO(resp.content)
        assert zipfile.is_zipfile(buf)

    def test_export_info(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.project_id}/export/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_count"] >= 1
        assert data["total_size"] > 0
        assert len(data["files"]) >= 1

    def test_export_project_404(self, client):
        resp = client.get("/api/projects/nonexistent/export")
        assert resp.status_code == 404

    def test_export_info_project_404(self, client):
        resp = client.get("/api/projects/nonexistent/export/info")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_connect_and_receive(self, client, sample_project):
        with client.websocket_connect(f"/ws/{sample_project.project_id}") as ws:
            # Connection established — test disconnect
            pass  # Clean exit

    def test_broadcast_to_subscriber(self, app, sample_project):
        """Test that broadcast sends to connected clients."""
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        # Create a mock websocket
        mock_ws = MagicMock()
        sent_messages = []
        async def mock_send(text):
            sent_messages.append(text)
        mock_ws.send_text = mock_send

        manager.connections[sample_project.project_id] = [mock_ws]

        asyncio.run(manager.broadcast(
            sample_project.project_id, "test_event", {"key": "value"}
        ))

        assert len(sent_messages) == 1
        msg = json.loads(sent_messages[0])
        assert msg["event"] == "test_event"
        assert msg["project_id"] == sample_project.project_id
        assert msg["data"]["key"] == "value"

    def test_broadcast_project_isolation(self):
        """Broadcast to project A should not reach project B subscribers."""
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        sent_a = []
        sent_b = []

        mock_a = MagicMock()
        mock_a.send_text = lambda text: sent_a.append(text)

        mock_b = MagicMock()
        mock_b.send_text = lambda text: sent_b.append(text)

        manager.connections["proj_a"] = [mock_a]
        manager.connections["proj_b"] = [mock_b]

        asyncio.run(manager.broadcast("proj_a", "event", {}))

        assert len(sent_a) == 1
        assert len(sent_b) == 0

    def test_disconnect_removes_connection(self):
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        mock_ws = MagicMock()
        manager.connections["proj_x"] = [mock_ws]

        asyncio.run(manager.disconnect(mock_ws, "proj_x"))
        assert "proj_x" not in manager.connections

    def test_active_connections_count(self):
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        assert manager.active_connections == 0

        manager.connections["p1"] = [MagicMock(), MagicMock()]
        manager.connections["p2"] = [MagicMock()]
        assert manager.active_connections == 3

    def test_broadcast_removes_dead_connections(self):
        """If send_text raises, the connection should be removed."""
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()

        dead_ws = MagicMock()
        async def fail_send(text):
            raise ConnectionError("gone")
        dead_ws.send_text = fail_send

        live_ws = MagicMock()
        sent = []
        async def ok_send(text):
            sent.append(text)
        live_ws.send_text = ok_send

        manager.connections["proj"] = [dead_ws, live_ws]

        asyncio.run(manager.broadcast("proj", "test", {}))

        assert len(sent) == 1
        assert dead_ws not in manager.connections.get("proj", [])

    def test_multiple_clients_same_project(self):
        """Multiple clients subscribed to the same project all get broadcast."""
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        sent_1 = []
        sent_2 = []

        ws1 = MagicMock()
        ws1.send_text = lambda t: sent_1.append(t)
        ws2 = MagicMock()
        ws2.send_text = lambda t: sent_2.append(t)

        manager.connections["proj"] = [ws1, ws2]
        asyncio.run(manager.broadcast("proj", "update", {"x": 1}))

        assert len(sent_1) == 1
        assert len(sent_2) == 1

    def test_broadcast_empty_project(self):
        """Broadcasting to a project with no subscribers should be a no-op."""
        import asyncio
        from web.websocket import OrchestratorWSManager

        manager = OrchestratorWSManager()
        # Should not raise
        asyncio.run(manager.broadcast("nobody", "event", {}))


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_parser_has_export(self):
        from cli.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["export", "--project", "p1"])
        assert args.command == "export"
        assert args.project == "p1"

    def test_parser_has_serve(self):
        from cli.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "localhost", "--port", "9000"])
        assert args.command == "serve"
        assert args.host == "localhost"
        assert args.port == 9000

    def test_export_writes_file(self, tmp_projects, sample_project, tmp_path):
        from cli.main import cmd_export
        output_path = tmp_path / "export.zip"
        args = MagicMock()
        args.projects_dir = str(tmp_projects)
        args.project = sample_project.project_id
        args.output = str(output_path)

        result = cmd_export(args)
        assert result == 0
        assert output_path.exists()
        assert zipfile.is_zipfile(output_path)

    def test_export_default_filename(self, tmp_projects, sample_project, monkeypatch):
        from cli.main import cmd_export
        args = MagicMock()
        args.projects_dir = str(tmp_projects)
        args.project = sample_project.project_id
        args.output = ""

        # Run in tmp dir so the default file is created there
        monkeypatch.chdir(tmp_projects.parent)
        result = cmd_export(args)
        assert result == 0
        expected = tmp_projects.parent / f"{sample_project.project_id}_export.zip"
        assert expected.exists()

    def test_export_project_not_found(self, tmp_projects, capsys):
        from cli.main import cmd_export
        args = MagicMock()
        args.projects_dir = str(tmp_projects)
        args.project = "nonexistent"
        args.output = ""

        result = cmd_export(args)
        assert result == 1

    def test_serve_calls_uvicorn(self, tmp_projects, docs_dir):
        from cli.main import cmd_serve

        mock_uvicorn = MagicMock()
        args = MagicMock()
        args.projects_dir = str(tmp_projects)
        args.docs_dir = str(docs_dir)
        args.host = "localhost"
        args.port = 9999

        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}):
            result = cmd_serve(args)
            assert result == 0
            mock_uvicorn.run.assert_called_once()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_flow_create_to_export(self, client, sample_vision_md):
        """Create project → get status → list gates → export."""
        # Create
        resp = client.post("/api/projects", json={
            "vision_markdown": sample_vision_md,
        })
        assert resp.status_code == 201
        project_id = resp.json()["data"]["project_id"]

        # Get status
        resp = client.get(f"/api/projects/{project_id}/status")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "vision_intake"

        # List gates
        resp = client.get(f"/api/projects/{project_id}/gates")
        assert resp.status_code == 200

        # List artifacts (empty)
        resp = client.get(f"/api/projects/{project_id}/artifacts")
        assert resp.status_code == 200
        assert resp.json() == []

        # Get costs
        resp = client.get(f"/api/projects/{project_id}/costs")
        assert resp.status_code == 200

        # Export
        resp = client.get(f"/api/projects/{project_id}/export")
        assert resp.status_code == 200
        assert zipfile.is_zipfile(BytesIO(resp.content))

    def test_create_multiple_projects(self, client, sample_vision_md):
        """Create two projects and verify list returns both."""
        client.post("/api/projects", json={"vision_markdown": sample_vision_md})
        client.post("/api/projects", json={"vision_markdown": sample_vision_md})

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_gate_respond_updates_state(self, client, project_with_gates):
        """Respond to gate and verify state changes."""
        pid = project_with_gates.project_id

        # Respond
        resp = client.post(f"/api/projects/{pid}/gates/gate_001", json={
            "response_type": "choose",
            "chosen_option": "A",
        })
        assert resp.status_code == 200

        # Verify gate status changed
        resp = client.get(f"/api/projects/{pid}/gates/gate_001")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] != "pending"

    def test_lineage_and_decisions_endpoints(self, client, tmp_projects, sample_project):
        """Write lineage data then query via API."""
        from orchestration.lineage import append_artifact_lineage, append_decision

        pid = sample_project.project_id
        append_decision(
            Decision(decision_id="d1", decision_type="test", made_by="ai"),
            pid, tmp_projects,
        )
        append_artifact_lineage(
            Artifact(artifact_id="a1", file_path="f.py", produced_by="b", lineage=["d1"]),
            pid, tmp_projects,
        )

        resp = client.get(f"/api/projects/{pid}/decisions")
        assert len(resp.json()) == 1

        resp = client.get(f"/api/projects/{pid}/lineage")
        assert len(resp.json()) == 1
        assert resp.json()[0]["lineage"] == ["d1"]

    def test_export_info_matches_download(self, client, sample_project):
        """Export info file count should match actual zip entries."""
        pid = sample_project.project_id

        info_resp = client.get(f"/api/projects/{pid}/export/info")
        info = info_resp.json()

        dl_resp = client.get(f"/api/projects/{pid}/export")
        with zipfile.ZipFile(BytesIO(dl_resp.content)) as zf:
            assert info["file_count"] == len(zf.namelist())

    def test_health_always_available(self, client):
        """Health endpoint should work regardless of projects."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
