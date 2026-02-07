"""Tier 4 tests — Builder Dispatch and Collection.

Tests use mock connectors (no real AI calls). Covers:
- Output parsing: JSON manifest from code block, raw JSON, fallback, code artifact extraction
- Artifact storage: save creates task dir, writes files, preserves content, manifest roundtrip
- BuilderSession: creates session with builder context, respects role config, dispatch
- BuilderDispatcher: single task, parallel group, sequential groups, all tasks, state updates
- ArchitectSession Phase 5: run_build_supervision, TIER_COMPLETE gate, artifacts, journal
- CLI: build command, requires correct phase, architect shows build prompt
- Models: BuildResult roundtrip
- Integration: full flow from task_queue → dispatch → artifacts → gate
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from orchestration.architect import ArchitectSession
from orchestration.builder_dispatch import (
    BuilderDispatcher,
    BuilderSession,
    extract_code_artifacts,
    load_builder_manifest,
    parse_builder_output,
    save_artifacts,
    save_builder_manifest,
)
from orchestration.constitution import ConstitutionEnforcer
from orchestration.gate_manager import GateManager
from orchestration.models import (
    BuilderOutputManifest,
    BuilderTaskContract,
    BuildResult,
    GateResponse,
    GateResponseType,
    GateStatus,
    GateType,
    Phase,
    TaskStatus,
    TaskType,
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
        purpose="Testing Tier 4",
        raw_markdown="# Test Project\n\n## Identity\n- Purpose: Testing Tier 4",
    )
    project = ProjectState(
        project_name="Test Project",
        vision_contract=vision,
        current_tier=1,
        current_phase="build_supervision",
        architecture_template="# Architecture\n\n## Subsystems\n- Core\n- API",
    )
    # Add task queue
    project.task_queue = [
        BuilderTaskContract(
            task_id="task_001",
            task_name="Define Core Schema",
            subsystem="Core",
            task_type="state_schema",
            objective="Define core data models",
            scope_must_build=["Data models", "Validation rules"],
            scope_must_not_touch=["UI layer"],
            test_criteria=["Models serialize", "Validation works"],
            depends_on=[],
            parallel_group=0,
            assigned_provider="builder_complex",
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
            assigned_provider="builder_simple",
        ),
        BuilderTaskContract(
            task_id="task_003",
            task_name="Build Auth Flow",
            subsystem="Auth",
            task_type="flow",
            objective="Implement authentication",
            scope_must_build=["Login flow", "Token management"],
            scope_must_not_touch=["UI"],
            test_criteria=["Login succeeds", "Token validates"],
            depends_on=["task_001"],
            parallel_group=1,
            assigned_provider="builder_complex",
        ),
    ]
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
            "max_iterations": 15,
        },
        "builder_simple": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "max_iterations": 10,
        },
    }


# ---------------------------------------------------------------------------
# Mock connector (same pattern as test_tier2/3)
# ---------------------------------------------------------------------------

@dataclass
class MockMessage:
    role: str = ""
    content: str = ""


@dataclass
class MockConnector:
    conversation_history: list = field(default_factory=list)
    session_id: str = "mock_builder_session"
    _responses: list = field(default_factory=list)
    _call_count: int = 0
    _system_prompt: str = ""

    async def send_message(self, message: str, **kwargs) -> dict:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Mock builder response"
        self._call_count += 1
        self.conversation_history.append(MockMessage(role="user", content=message))
        self.conversation_history.append(MockMessage(role="assistant", content=content))
        return {"content": content, "usage": {"input": 500, "output": 250}}


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
# Sample builder responses
# ---------------------------------------------------------------------------

SAMPLE_BUILDER_RESPONSE_WITH_JSON = '''\
# File: src/core/state.py
```python
class GameState:
    """Core state model."""
    def __init__(self):
        self.entities = {}
        self.tick = 0
```

# File: tests/test_state.py
```python
def test_game_state_init():
    state = GameState()
    assert state.tick == 0
```

```json
{
  "task_id": "task_001",
  "artifacts": [
    {"file": "src/core/state.py", "implements": "Core state model"},
    {"file": "tests/test_state.py", "implements": "State model tests"}
  ],
  "incomplete": [],
  "questions_for_architect": []
}
```
'''

SAMPLE_BUILDER_RESPONSE_RAW_JSON = '''\
Here is the implementation.

{"task_id": "task_002", "artifacts": [{"file": "src/api.py", "implements": "API endpoints"}], "incomplete": [], "questions_for_architect": ["Should we use REST or GraphQL?"]}
'''

SAMPLE_BUILDER_RESPONSE_NO_JSON = '''\
Here is the implementation of the auth flow.

# File: src/auth/login.py
```python
def login(username, password):
    return {"token": "abc123"}
```

I couldn't produce a proper manifest but the code above implements the login flow.
'''

SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS = '''\
# File: src/core/models.py
```python
class User:
    pass
```

```json
{
  "task_id": "task_001",
  "artifacts": [
    {"file": "src/core/models.py", "implements": "User model"}
  ],
  "incomplete": [
    {"item": "Admin role", "reason": "Need clarification on permissions"}
  ],
  "questions_for_architect": [
    "Should admin users have delete permissions?",
    "What is the session timeout?"
  ]
}
```
'''


# ---------------------------------------------------------------------------
# Output parsing tests
# ---------------------------------------------------------------------------

class TestOutputParsing:
    def test_parse_json_code_block(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_WITH_JSON, "task_001")
        assert manifest.task_id == "task_001"
        assert len(manifest.artifacts) == 2
        assert manifest.artifacts[0]["file"] == "src/core/state.py"

    def test_parse_raw_json(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_RAW_JSON, "task_002")
        assert manifest.task_id == "task_002"
        assert len(manifest.artifacts) == 1
        assert manifest.artifacts[0]["file"] == "src/api.py"

    def test_parse_raw_json_questions(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_RAW_JSON, "task_002")
        assert len(manifest.questions_for_architect) == 1
        assert "REST" in manifest.questions_for_architect[0]

    def test_parse_fallback_no_json(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_NO_JSON, "task_003")
        assert manifest.task_id == "task_003"
        assert manifest.artifacts == []

    def test_parse_empty_response(self):
        manifest = parse_builder_output("", "task_empty")
        assert manifest.task_id == "task_empty"
        assert manifest.artifacts == []

    def test_parse_questions_for_architect(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS, "task_001")
        assert len(manifest.questions_for_architect) == 2
        assert "admin" in manifest.questions_for_architect[0].lower()

    def test_parse_incomplete_items(self):
        manifest = parse_builder_output(SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS, "task_001")
        assert len(manifest.incomplete) == 1
        assert manifest.incomplete[0]["item"] == "Admin role"

    def test_parse_default_task_id(self):
        """If JSON has no task_id, the provided one is used."""
        text = '```json\n{"artifacts": [{"file": "x.py"}]}\n```'
        manifest = parse_builder_output(text, "my_task")
        assert manifest.task_id == "my_task"

    def test_parse_invalid_json_falls_through(self):
        text = '```json\n{invalid json}\n```'
        manifest = parse_builder_output(text, "task_bad")
        assert manifest.task_id == "task_bad"
        assert manifest.artifacts == []


class TestCodeArtifactExtraction:
    def test_extract_single_file(self):
        text = '# File: src/main.py\n```python\nprint("hello")\n```'
        artifacts = extract_code_artifacts(text)
        assert len(artifacts) == 1
        assert artifacts[0][0] == "src/main.py"
        assert 'print("hello")' in artifacts[0][1]

    def test_extract_multiple_files(self):
        artifacts = extract_code_artifacts(SAMPLE_BUILDER_RESPONSE_WITH_JSON)
        assert len(artifacts) == 2
        paths = [a[0] for a in artifacts]
        assert "src/core/state.py" in paths
        assert "tests/test_state.py" in paths

    def test_extract_no_files(self):
        text = "Just some text without any file headers."
        artifacts = extract_code_artifacts(text)
        assert artifacts == []

    def test_extract_preserves_content(self):
        text = '# File: config.json\n```json\n{"key": "value"}\n```'
        artifacts = extract_code_artifacts(text)
        assert len(artifacts) == 1
        assert '"key": "value"' in artifacts[0][1]

    def test_extract_mixed_languages(self):
        text = (
            '# File: src/app.py\n```python\nimport os\n```\n\n'
            '# File: src/style.css\n```css\nbody { margin: 0; }\n```\n\n'
            '# File: src/index.html\n```html\n<html></html>\n```'
        )
        artifacts = extract_code_artifacts(text)
        assert len(artifacts) == 3

    def test_extract_with_nested_content(self):
        text = '# File: src/main.py\n```python\ndef foo():\n    return "bar"\n```'
        artifacts = extract_code_artifacts(text)
        assert len(artifacts) == 1
        assert "def foo():" in artifacts[0][1]


# ---------------------------------------------------------------------------
# Artifact storage tests
# ---------------------------------------------------------------------------

class TestArtifactStorage:
    def test_save_creates_task_dir(self, tmp_projects):
        artifacts = [("src/main.py", "print('hello')")]
        save_artifacts(artifacts, "proj_1", "task_001", tmp_projects)
        assert (tmp_projects / "proj_1" / "artifacts" / "task_001").is_dir()

    def test_save_writes_file(self, tmp_projects):
        artifacts = [("src/main.py", "print('hello')")]
        paths = save_artifacts(artifacts, "proj_1", "task_001", tmp_projects)
        assert len(paths) == 1
        assert paths[0].exists()
        assert paths[0].read_text() == "print('hello')"

    def test_save_preserves_content(self, tmp_projects):
        content = 'class Foo:\n    def bar(self):\n        return 42\n'
        artifacts = [("src/foo.py", content)]
        paths = save_artifacts(artifacts, "proj_1", "task_001", tmp_projects)
        assert paths[0].read_text() == content

    def test_save_multiple_files(self, tmp_projects):
        artifacts = [
            ("src/a.py", "# file a"),
            ("src/b.py", "# file b"),
            ("tests/test_a.py", "# test a"),
        ]
        paths = save_artifacts(artifacts, "proj_1", "task_001", tmp_projects)
        assert len(paths) == 3
        assert all(p.exists() for p in paths)

    def test_save_nested_paths(self, tmp_projects):
        artifacts = [("src/core/deep/module.py", "# deep")]
        paths = save_artifacts(artifacts, "proj_1", "task_001", tmp_projects)
        assert paths[0].exists()
        assert "deep" in str(paths[0])

    def test_manifest_save_and_load(self, tmp_projects):
        manifest = BuilderOutputManifest(
            task_id="task_001",
            builder_session_id="session_1",
            completed_at="2026-02-06T00:00:00Z",
            artifacts=[{"file": "src/main.py", "implements": "Main module"}],
            incomplete=[],
            questions_for_architect=["Question 1"],
            token_usage={"input": 100, "output": 50},
        )
        path = save_builder_manifest(manifest, "proj_1", tmp_projects)
        assert path.exists()

        loaded = load_builder_manifest("task_001", "proj_1", tmp_projects)
        assert loaded.task_id == "task_001"
        assert loaded.builder_session_id == "session_1"
        assert len(loaded.artifacts) == 1
        assert loaded.questions_for_architect == ["Question 1"]

    def test_load_nonexistent_manifest(self, tmp_projects):
        with pytest.raises(FileNotFoundError):
            load_builder_manifest("nonexistent", "proj_1", tmp_projects)


# ---------------------------------------------------------------------------
# BuilderSession tests
# ---------------------------------------------------------------------------

class TestBuilderSession:
    def test_create_session_uses_builder_context(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Test Task",
            task_type="state_schema",
            subsystem="Core",
        )
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory()

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock-model"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )
        connector = session.create_session()

        # Verify the system prompt is builder context, not architect context
        assert "BUILDER ROLE" in connector._system_prompt
        assert "ARCHITECT ROLE" not in connector._system_prompt

    def test_create_session_respects_role_config(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(task_id="task_001", task_name="Test")
        constitution = ConstitutionEnforcer(docs_dir)

        created_with = {}

        def tracking_factory(provider="", model="", system_prompt="", **kwargs):
            created_with["provider"] = provider
            created_with["model"] = model
            return MockConnector(_system_prompt=system_prompt)

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=tracking_factory,
            role_config={"provider": "deepseek", "model": "deepseek-chat"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )
        session.create_session()

        assert created_with["provider"] == "deepseek"
        assert created_with["model"] == "deepseek-chat"

    def test_dispatch_sends_prompt(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Test Task",
            objective="Build something",
        )
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        manifest = asyncio.run(session.dispatch())

        assert manifest.task_id == "task_001"
        # Verify prompt was sent (conversation history has user + assistant messages)
        assert len(session.connector.conversation_history) == 2

    def test_dispatch_returns_manifest(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(task_id="task_001", task_name="Test")
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        manifest = asyncio.run(session.dispatch())

        assert isinstance(manifest, BuilderOutputManifest)
        assert manifest.task_id == "task_001"
        assert manifest.builder_session_id == "mock_builder_session"

    def test_dispatch_saves_session(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(task_id="task_001", task_name="Test")
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        asyncio.run(session.dispatch())

        session_path = tmp_projects / "proj_test" / "builder_sessions" / "task_001.json"
        assert session_path.exists()
        data = json.loads(session_path.read_text())
        assert data["task_id"] == "task_001"
        assert len(data["messages"]) == 2

    def test_dispatch_saves_code_artifacts(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(task_id="task_001", task_name="Test")
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        asyncio.run(session.dispatch())

        artifact_dir = tmp_projects / "proj_test" / "artifacts" / "task_001"
        assert artifact_dir.is_dir()
        assert (artifact_dir / "src" / "core" / "state.py").exists()

    def test_dispatch_tracks_token_usage(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(task_id="task_001", task_name="Test")
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "test_provider", "model": "test_model"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        manifest = asyncio.run(session.dispatch())

        usage = manifest.token_usage
        assert usage["input"] == 500
        assert usage["output"] == 250
        assert usage["provider"] == "test_provider"

    def test_execution_prompt_contains_task_info(self, docs_dir, tmp_projects):
        task = BuilderTaskContract(
            task_id="task_001",
            task_name="Build Auth",
            objective="Implement authentication",
            scope_must_build=["Login flow"],
            test_criteria=["Login works"],
        )
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory(["response"])

        session = BuilderSession(
            task=task,
            constitution=constitution,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
            projects_dir=tmp_projects,
            project_id="proj_test",
        )

        prompt = session._build_execution_prompt()

        assert "task_001" in prompt
        assert "Build Auth" in prompt
        assert "Implement authentication" in prompt
        assert "Login flow" in prompt
        assert "Login works" in prompt
        assert "# File:" in prompt  # output format instructions


# ---------------------------------------------------------------------------
# BuilderDispatcher tests
# ---------------------------------------------------------------------------

class TestBuilderDispatcher:
    def _make_dispatcher(self, project, tmp_projects, docs_dir, roles_config, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory(responses or [SAMPLE_BUILDER_RESPONSE_WITH_JSON])
        return BuilderDispatcher(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=factory,
            roles_config=roles_config,
        )

    def test_dispatch_single_task(self, sample_project, tmp_projects, docs_dir, roles_config):
        # Simplify to one task
        sample_project.task_queue = [sample_project.task_queue[0]]

        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        assert result.completed_count == 1
        assert result.failed_count == 0
        assert len(result.manifests) == 1

    def test_dispatch_all_tasks(self, sample_project, tmp_projects, docs_dir, roles_config):
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        assert result.completed_count == 3
        assert result.failed_count == 0
        assert len(result.manifests) == 3

    def test_dispatch_parallel_group(self, sample_project, tmp_projects, docs_dir, roles_config):
        """Tasks in same parallel_group should all get dispatched."""
        # task_002 and task_003 are both in group 1
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        # All 3 tasks dispatched (group 0 has 1 task, group 1 has 2 tasks)
        assert result.completed_count == 3

    def test_dispatch_sequential_groups(self, sample_project, tmp_projects, docs_dir, roles_config):
        """Groups should be dispatched in order (0 before 1)."""
        dispatch_order = []

        original_factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        def tracking_factory(provider="", model="", system_prompt="", **kwargs):
            connector = original_factory(provider, model, system_prompt, **kwargs)
            original_send = connector.send_message

            async def tracked_send(message, **kw):
                dispatch_order.append(message)
                return await original_send(message, **kw)

            connector.send_message = tracked_send
            return connector

        constitution = ConstitutionEnforcer(docs_dir)
        dispatcher = BuilderDispatcher(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=tracking_factory,
            roles_config=roles_config,
        )
        asyncio.run(dispatcher.dispatch_all())

        # Group 0 (task_001) should dispatch before group 1 (task_002, task_003)
        assert len(dispatch_order) == 3
        # First dispatch should contain task_001's info
        assert "task_001" in dispatch_order[0] or "Define Core Schema" in dispatch_order[0]

    def test_dispatch_updates_task_status(self, sample_project, tmp_projects, docs_dir, roles_config):
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        asyncio.run(dispatcher.dispatch_all())

        # All tasks should be marked completed
        all_tasks = sample_project.task_queue + sample_project.completed_tasks
        for task in all_tasks:
            assert task.status == TaskStatus.COMPLETED.value

    def test_dispatch_accumulates_tokens(self, sample_project, tmp_projects, docs_dir, roles_config):
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        # Each mock returns 500 input, 250 output tokens
        assert result.total_input_tokens == 1500  # 3 tasks * 500
        assert result.total_output_tokens == 750   # 3 tasks * 250

    def test_dispatch_empty_queue(self, sample_project, tmp_projects, docs_dir, roles_config):
        sample_project.task_queue = []
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        assert result.completed_count == 0
        assert result.failed_count == 0
        assert result.manifests == []

    def test_role_config_selection_complex(self, sample_project, tmp_projects, docs_dir, roles_config):
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        # task_001 has assigned_provider="builder_complex"
        config = dispatcher._get_role_config(sample_project.task_queue[0])
        assert config["provider"] == "anthropic"

    def test_role_config_selection_simple(self, sample_project, tmp_projects, docs_dir, roles_config):
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, roles_config,
        )
        # task_002 has assigned_provider="builder_simple"
        config = dispatcher._get_role_config(sample_project.task_queue[1])
        assert config["provider"] == "deepseek"

    def test_role_config_fallback(self, sample_project, tmp_projects, docs_dir):
        """When no matching config, falls back to builder_complex."""
        dispatcher = self._make_dispatcher(
            sample_project, tmp_projects, docs_dir, {},
        )
        task = BuilderTaskContract(assigned_provider="unknown")
        config = dispatcher._get_role_config(task)
        # Should fallback to default dict
        assert "provider" in config

    def test_dispatch_collects_questions(self, sample_project, tmp_projects, docs_dir, roles_config):
        sample_project.task_queue = [sample_project.task_queue[0]]

        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS])
        dispatcher = BuilderDispatcher(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=factory,
            roles_config=roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        assert len(result.questions_for_architect) == 2
        assert "admin" in result.questions_for_architect[0].lower()

    def test_dispatch_collects_incomplete(self, sample_project, tmp_projects, docs_dir, roles_config):
        sample_project.task_queue = [sample_project.task_queue[0]]

        constitution = ConstitutionEnforcer(docs_dir)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS])
        dispatcher = BuilderDispatcher(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            connector_factory=factory,
            roles_config=roles_config,
        )
        result = asyncio.run(dispatcher.dispatch_all())

        assert len(result.incomplete_items) == 1


# ---------------------------------------------------------------------------
# ArchitectSession Phase 5 tests
# ---------------------------------------------------------------------------

class TestArchitectPhase5:
    def _make_session(self, project, tmp_projects, docs_dir, responses=None):
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        factory = mock_connector_factory(responses or [SAMPLE_BUILDER_RESPONSE_WITH_JSON])
        return ArchitectSession(
            project=project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock-model"},
        )

    def test_run_build_supervision_dispatches(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_build_supervision())

        assert gate is not None
        assert gate.gate_type == GateType.TIER_COMPLETE.value

    def test_run_build_supervision_creates_tier_complete_gate(
        self, sample_project, tmp_projects, docs_dir
    ):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_build_supervision())

        assert gate.gate_type == "tier_complete"
        assert gate.status == "pending"
        assert sample_project.pending_gate is gate

    def test_run_build_supervision_gate_summary(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        gate = asyncio.run(session.run_build_supervision())

        assert "3 tasks completed" in gate.summary
        assert "0 failed" in gate.summary

    def test_run_build_supervision_moves_tasks(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_build_supervision())

        # Completed tasks moved from queue to completed_tasks
        assert len(sample_project.completed_tasks) == 3
        assert len(sample_project.task_queue) == 0

    def test_run_build_supervision_stores_artifacts(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_build_supervision())

        # Check that builder outputs directory was created
        outputs_dir = tmp_projects / sample_project.project_id / "builder_outputs"
        assert outputs_dir.is_dir()
        # At least one manifest file
        manifest_files = list(outputs_dir.glob("*.json"))
        assert len(manifest_files) >= 1

    def test_run_build_supervision_journal_entry(self, sample_project, tmp_projects, docs_dir):
        from orchestration.journal import journal_path_for_project, load_entries

        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_build_supervision())

        jpath = journal_path_for_project(sample_project.project_id, tmp_projects)
        entries = load_entries(jpath)
        assert len(entries) >= 1
        assert "dispatched" in entries[-1].lower() or "build" in entries[-1].lower()

    def test_run_build_supervision_build_result(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_build_supervision())

        build_result = session._build_result
        assert isinstance(build_result, BuildResult)
        assert build_result.completed_count == 3
        assert build_result.total_input_tokens == 1500
        assert build_result.total_output_tokens == 750

    def test_run_build_supervision_with_questions(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(
            sample_project, tmp_projects, docs_dir,
            responses=[SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS],
        )
        gate = asyncio.run(session.run_build_supervision())

        # Gate should include builder questions
        assert len(gate.questions) > 0

    def test_run_build_supervision_custom_builder_factory(
        self, sample_project, tmp_projects, docs_dir
    ):
        """Verify that a separate builder factory can be injected."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)

        builder_factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])
        architect_factory = mock_connector_factory()

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=architect_factory,
            role_config={"provider": "mock", "model": "mock"},
        )

        gate = asyncio.run(session.run_build_supervision(
            builder_connector_factory=builder_factory,
        ))

        assert gate.gate_type == "tier_complete"
        assert gate.status == "pending"

    def test_run_build_supervision_saves_project(self, sample_project, tmp_projects, docs_dir):
        session = self._make_session(sample_project, tmp_projects, docs_dir)
        asyncio.run(session.run_build_supervision())

        reloaded = ProjectState.load(sample_project.project_id, tmp_projects)
        assert reloaded.pending_gate is not None
        assert reloaded.pending_gate.gate_type == "tier_complete"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_build_command_dispatches(self, sample_project, tmp_projects, docs_dir, capsys, monkeypatch):
        """Build command dispatches tasks and shows results."""
        from cli.main import main

        # Patch ArchitectSession to use mock
        import orchestration.architect as arch_mod

        original_init = ArchitectSession.__init__

        def patched_init(self_session, *args, **kwargs):
            original_init(self_session, *args, **kwargs)
            self_session.connector_factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        monkeypatch.setattr(ArchitectSession, "__init__", patched_init)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "build",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "Dispatching" in out
        assert "Completed" in out

    def test_build_requires_build_supervision_phase(self, tmp_projects, docs_dir, capsys):
        from cli.main import main

        # Create project in wrong phase
        project = ProjectState(
            project_name="Wrong Phase",
            current_phase="system_design",
        )
        project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "build",
            "--project", project.project_id,
        ])

        assert result == 1
        err = capsys.readouterr().err
        assert "build_supervision" in err

    def test_build_blocked_by_pending_gate(self, sample_project, tmp_projects, docs_dir, capsys):
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            sample_project,
            GateType.TIER_COMPLETE,
            "Previous build pending review",
        )
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "build",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "approve" in out.lower() or "reject" in out.lower()

    def test_architect_shows_build_prompt(self, sample_project, tmp_projects, docs_dir, capsys):
        """Architect command in build_supervision phase prompts to run build."""
        from cli.main import main

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "build" in out.lower()

    def test_architect_shows_completion_after_tier_complete(
        self, sample_project, tmp_projects, docs_dir, capsys
    ):
        """After TIER_COMPLETE gate is resolved, architect shows completion."""
        from cli.main import main

        gm = GateManager(tmp_projects)
        gate = gm.create_gate(
            sample_project,
            GateType.TIER_COMPLETE,
            "Build complete",
        )
        # Resolve the gate
        response = GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option="A",
        )
        gm.respond_to_gate(sample_project, gate.gate_id, response)
        sample_project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "architect",
            "--project", sample_project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "complete" in out.lower()

    def test_build_empty_queue(self, tmp_projects, docs_dir, capsys):
        from cli.main import main

        project = ProjectState(
            project_name="Empty Queue",
            current_phase="build_supervision",
        )
        project.task_queue = []
        project.save(tmp_projects)

        result = main([
            "--projects-dir", str(tmp_projects),
            "--docs-dir", str(docs_dir),
            "build",
            "--project", project.project_id,
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "No tasks" in out


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_build_result_roundtrip(self):
        result = BuildResult(
            manifests=[{"task_id": "t1"}, {"task_id": "t2"}],
            total_cost=1.25,
            total_input_tokens=5000,
            total_output_tokens=2500,
            completed_count=2,
            failed_count=0,
            incomplete_items=[{"item": "X", "reason": "Y"}],
            questions_for_architect=["Q1", "Q2"],
        )
        d = result.to_dict()
        loaded = BuildResult.from_dict(d)

        assert loaded.completed_count == 2
        assert loaded.total_cost == 1.25
        assert loaded.total_input_tokens == 5000
        assert loaded.total_output_tokens == 2500
        assert len(loaded.manifests) == 2
        assert len(loaded.questions_for_architect) == 2
        assert len(loaded.incomplete_items) == 1

    def test_build_result_defaults(self):
        result = BuildResult()
        assert result.completed_count == 0
        assert result.total_cost == 0.0
        assert result.manifests == []
        assert result.questions_for_architect == []

    def test_build_result_json(self):
        result = BuildResult(completed_count=5, total_cost=2.5)
        json_str = result.to_json()
        data = json.loads(json_str)
        assert data["completed_count"] == 5
        assert data["total_cost"] == 2.5

    def test_gate_type_tier_complete(self):
        assert GateType.TIER_COMPLETE.value == "tier_complete"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_flow_task_queue_to_gate(self, sample_project, tmp_projects, docs_dir):
        """Full flow: task_queue → dispatch → artifacts → TIER_COMPLETE gate."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )

        # Dispatch
        gate = asyncio.run(session.run_build_supervision())

        # Verify gate
        assert gate.gate_type == "tier_complete"
        assert gate.status == "pending"

        # Verify artifacts on disk
        outputs_dir = tmp_projects / sample_project.project_id / "builder_outputs"
        assert len(list(outputs_dir.glob("*.json"))) >= 1

        # Verify project state
        assert len(sample_project.completed_tasks) == 3
        assert len(sample_project.task_queue) == 0
        assert sample_project.pending_gate is gate

        # Verify build result
        build_result = session._build_result
        assert build_result.completed_count == 3
        assert build_result.total_input_tokens == 1500

        # Verify builder sessions saved
        sessions_dir = tmp_projects / sample_project.project_id / "builder_sessions"
        assert sessions_dir.is_dir()
        session_files = list(sessions_dir.glob("*.json"))
        assert len(session_files) == 3

    def test_full_flow_with_project_reload(self, sample_project, tmp_projects, docs_dir):
        """After dispatch, project state can be reloaded from disk."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)
        factory = mock_connector_factory([SAMPLE_BUILDER_RESPONSE_WITH_JSON])

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=factory,
            role_config={"provider": "mock", "model": "mock"},
        )

        asyncio.run(session.run_build_supervision())

        # Reload from disk
        reloaded = ProjectState.load(sample_project.project_id, tmp_projects)
        assert len(reloaded.completed_tasks) == 3
        assert len(reloaded.task_queue) == 0
        assert reloaded.pending_gate is not None
        assert reloaded.pending_gate.gate_type == "tier_complete"

    def test_flow_with_mixed_responses(self, sample_project, tmp_projects, docs_dir):
        """Dispatch with mixed builder responses (JSON, questions, no JSON)."""
        constitution = ConstitutionEnforcer(docs_dir)
        gate_manager = GateManager(tmp_projects)

        # Each task gets a different response
        responses = [
            SAMPLE_BUILDER_RESPONSE_WITH_JSON,
            SAMPLE_BUILDER_RESPONSE_WITH_QUESTIONS,
            SAMPLE_BUILDER_RESPONSE_NO_JSON,
        ]

        # Use a factory that cycles through responses for each connector
        call_count = [0]

        def cycling_factory(provider="", model="", system_prompt="", **kwargs):
            idx = call_count[0] % len(responses)
            call_count[0] += 1
            return MockConnector(
                _responses=[responses[idx]],
                _system_prompt=system_prompt,
            )

        session = ArchitectSession(
            project=sample_project,
            projects_dir=tmp_projects,
            constitution=constitution,
            gate_manager=gate_manager,
            connector_factory=cycling_factory,
            role_config={"provider": "mock", "model": "mock"},
        )

        gate = asyncio.run(session.run_build_supervision())

        assert gate.gate_type == "tier_complete"
        build_result = session._build_result
        assert build_result.completed_count == 3
        # Should have collected questions from the second response
        assert len(build_result.questions_for_architect) >= 2
