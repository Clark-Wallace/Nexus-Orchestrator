"""Builder Dispatch — dispatches tasks to isolated AI builder sessions.

Tier 4: Takes the ordered task_queue from Tier 3 and dispatches each task to
an isolated NexusConnector session. Collects code artifacts and structured
manifests, stores everything for review.

Flow:
1. Group tasks by parallel_group
2. Dispatch groups sequentially (0 → 1 → 2...)
3. Within each group, dispatch tasks concurrently via asyncio.gather
4. Collect BuilderOutputManifest + code artifacts per task
5. Aggregate into BuildResult for the tier
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestration.constitution import ConstitutionEnforcer
from orchestration.lineage import append_usage as _append_usage
from orchestration.models import (
    BuilderOutputManifest,
    BuilderTaskContract,
    BuildResult,
    TaskStatus,
    TokenUsage,
)
from orchestration.project_state import generate_id


# ---------------------------------------------------------------------------
# Connector protocol (reuse from architect.py)
# ---------------------------------------------------------------------------

class ConnectorProtocol(Protocol):
    """Minimal interface we need from NexusConnector."""
    conversation_history: list
    session_id: str

    async def send_message(self, message: str, **kwargs: Any) -> dict[str, Any]: ...


ConnectorFactory = Callable[..., ConnectorProtocol]


# ---------------------------------------------------------------------------
# Builder Session — one task, one isolated AI session
# ---------------------------------------------------------------------------

class BuilderSession:
    """Manages a single builder's isolated Nexus session for one task."""

    def __init__(
        self,
        task: BuilderTaskContract,
        constitution: ConstitutionEnforcer,
        connector_factory: ConnectorFactory,
        role_config: dict,
        projects_dir: str | Path,
        project_id: str,
    ):
        self.task = task
        self.constitution = constitution
        self.connector_factory = connector_factory
        self.role_config = role_config
        self.projects_dir = Path(projects_dir)
        self.project_id = project_id
        self.connector: ConnectorProtocol | None = None

    def create_session(self) -> ConnectorProtocol:
        """Create the builder connector with task-specific constitutional context."""
        system_prompt = self.constitution.build_builder_context(self.task)

        self.connector = self.connector_factory(
            provider=self.role_config.get("provider", "anthropic"),
            model=self.role_config.get("model", "claude-sonnet-4-5-20250929"),
            system_prompt=system_prompt,
        )
        return self.connector

    async def dispatch(self) -> BuilderOutputManifest:
        """Send execution prompt, collect response, parse into manifest.

        Returns BuilderOutputManifest with artifacts and token usage.
        """
        if not self.connector:
            self.create_session()

        prompt = self._build_execution_prompt()
        response = await self.connector.send_message(prompt)
        content = response.get("content", "")
        usage = response.get("usage", {})

        # Parse manifest from response
        manifest = parse_builder_output(content, self.task.task_id)

        # Set session info
        manifest.builder_session_id = getattr(
            self.connector, "session_id", "session_unknown"
        )
        manifest.completed_at = datetime.now(timezone.utc).isoformat()

        # Set token usage
        manifest.token_usage = TokenUsage(
            input=usage.get("input", 0),
            output=usage.get("output", 0),
            provider=self.role_config.get("provider", ""),
            model=self.role_config.get("model", ""),
        ).to_dict()

        # Tier 6: track builder usage
        _append_usage(
            usage_entry={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_id": self.task.task_id,
                "role": "builder",
                "provider": self.role_config.get("provider", ""),
                "model": self.role_config.get("model", ""),
                "input_tokens": usage.get("input", 0),
                "output_tokens": usage.get("output", 0),
                "estimated_cost": usage.get("estimated_cost", 0.0),
                "phase": "build_supervision",
                "tier": self.task.build_tier,
            },
            project_id=self.project_id,
            projects_dir=self.projects_dir,
        )

        # Extract and save code artifacts
        code_artifacts = extract_code_artifacts(content)
        if code_artifacts:
            saved_paths = save_artifacts(
                code_artifacts, self.project_id, self.task.task_id, self.projects_dir
            )
            # Add saved paths to manifest artifacts if not already there
            for path, _ in code_artifacts:
                found = False
                for art in manifest.artifacts:
                    if isinstance(art, dict) and art.get("file") == path:
                        found = True
                        break
                if not found:
                    manifest.artifacts.append({"file": path, "implements": ""})

        # Save manifest
        save_builder_manifest(manifest, self.project_id, self.projects_dir)

        # Save session
        self.save_session()

        return manifest

    def _build_execution_prompt(self) -> str:
        """Format the task contract + output format instructions."""
        lines = [
            "Execute the following Builder Task Contract.\n",
            f"Task ID: {self.task.task_id}",
            f"Task Name: {self.task.task_name}",
            f"Subsystem: {self.task.subsystem}",
            f"Objective: {self.task.objective}",
            "",
            "Must Build:",
        ]
        for item in self.task.scope_must_build:
            lines.append(f"  - {item}")

        lines.append("\nMust NOT Touch:")
        for item in self.task.scope_must_not_touch:
            lines.append(f"  - {item}")

        lines.append("\nTest Criteria:")
        for tc in self.task.test_criteria:
            lines.append(f"  - {tc}")

        lines.extend([
            "",
            "OUTPUT FORMAT:",
            "1. For each file you produce, use this header format:",
            "   # File: path/to/file.py",
            "   ```python",
            "   <code>",
            "   ```",
            "",
            "2. After all code, produce a JSON manifest block:",
            "   ```json",
            "   {",
            '     "task_id": "<task_id>",',
            '     "artifacts": [',
            '       {"file": "path/to/file.py", "implements": "description"}',
            "     ],",
            '     "incomplete": [],',
            '     "questions_for_architect": []',
            "   }",
            "   ```",
        ])

        return "\n".join(lines)

    def save_session(self) -> None:
        """Persist builder conversation to builder_sessions/{task_id}.json."""
        if not self.connector:
            return

        session_dir = self.projects_dir / self.project_id / "builder_sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        messages = []
        for msg in self.connector.conversation_history:
            if hasattr(msg, "role"):
                messages.append({
                    "role": msg.role,
                    "content": msg.content if hasattr(msg, "content") else str(msg),
                })
            elif isinstance(msg, dict):
                messages.append(msg)

        data = {
            "task_id": self.task.task_id,
            "session_id": getattr(self.connector, "session_id", ""),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "messages": messages,
        }

        path = session_dir / f"{self.task.task_id}.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Builder Dispatcher — orchestrates all tasks
# ---------------------------------------------------------------------------

class BuilderDispatcher:
    """Orchestrates dispatching all tasks with dependency awareness."""

    def __init__(
        self,
        project,
        projects_dir: str | Path,
        constitution: ConstitutionEnforcer,
        connector_factory: ConnectorFactory,
        roles_config: dict,
    ):
        self.project = project
        self.projects_dir = Path(projects_dir)
        self.constitution = constitution
        self.connector_factory = connector_factory
        self.roles_config = roles_config

    async def dispatch_all(self) -> BuildResult:
        """Dispatch all tasks respecting parallel groups.

        Groups dispatched sequentially (0 → 1 → 2...).
        Tasks within each group dispatched concurrently.
        """
        tasks = self.project.task_queue
        if not tasks:
            return BuildResult()

        # Group tasks by parallel_group
        groups: dict[int, list[BuilderTaskContract]] = defaultdict(list)
        for task in tasks:
            groups[task.parallel_group].append(task)

        all_manifests: list[BuilderOutputManifest] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        failed_count = 0
        all_incomplete: list[dict] = []
        all_questions: list[str] = []

        # Dispatch groups in order
        for group_num in sorted(groups.keys()):
            group_tasks = groups[group_num]
            manifests = await self.dispatch_group(group_tasks)

            for manifest in manifests:
                all_manifests.append(manifest)
                usage = manifest.token_usage
                if isinstance(usage, dict):
                    total_input += usage.get("input", 0)
                    total_output += usage.get("output", 0)
                    total_cost += usage.get("estimated_cost", 0.0)
                all_incomplete.extend(manifest.incomplete)
                all_questions.extend(manifest.questions_for_architect)

        completed_count = len(all_manifests) - failed_count

        return BuildResult(
            manifests=[m.to_dict() for m in all_manifests],
            total_cost=total_cost,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            completed_count=completed_count,
            failed_count=failed_count,
            incomplete_items=all_incomplete,
            questions_for_architect=all_questions,
        )

    async def dispatch_group(
        self, tasks: list[BuilderTaskContract]
    ) -> list[BuilderOutputManifest]:
        """Dispatch all tasks in one parallel group concurrently."""
        coros = [self.dispatch_single(task) for task in tasks]
        return await asyncio.gather(*coros)

    async def dispatch_single(
        self, task: BuilderTaskContract
    ) -> BuilderOutputManifest:
        """Create BuilderSession, dispatch, update task status, return manifest."""
        role_config = self._get_role_config(task)

        session = BuilderSession(
            task=task,
            constitution=self.constitution,
            connector_factory=self.connector_factory,
            role_config=role_config,
            projects_dir=self.projects_dir,
            project_id=self.project.project_id,
        )

        # Update task status
        task.status = TaskStatus.DISPATCHED.value

        manifest = await session.dispatch()

        # Update task status to completed
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.now(timezone.utc).isoformat()

        return manifest

    def _get_role_config(self, task: BuilderTaskContract) -> dict:
        """Resolve task's assigned_provider to the correct role config."""
        provider_str = task.assigned_provider or ""

        # Check if it matches a role name directly
        if provider_str in self.roles_config:
            return self.roles_config[provider_str]

        # Check if the provider string contains info from a known role
        for role_name in ("builder_complex", "builder_simple"):
            role_cfg = self.roles_config.get(role_name, {})
            provider = role_cfg.get("provider", "")
            model = role_cfg.get("model", "")
            if provider and provider in provider_str:
                return role_cfg

        # Fallback: use builder_complex config or defaults
        return self.roles_config.get("builder_complex", {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
        })


# ---------------------------------------------------------------------------
# Parsing helpers (pure functions)
# ---------------------------------------------------------------------------

def parse_builder_output(response_text: str, task_id: str) -> BuilderOutputManifest:
    """Parse builder response into a BuilderOutputManifest.

    Three-tier strategy:
    1. JSON code block (```json containing manifest keys)
    2. Raw JSON with task_id/artifacts keys
    3. Fallback: minimal manifest from response text
    """
    # Strategy 1: JSON code block
    json_blocks = re.findall(
        r"```json\s*\n(.*?)```", response_text, re.DOTALL
    )
    for block in json_blocks:
        try:
            data = json.loads(block.strip())
            if isinstance(data, dict) and ("task_id" in data or "artifacts" in data):
                data.setdefault("task_id", task_id)
                return BuilderOutputManifest.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 2: Raw JSON with manifest keys — find balanced braces
    try:
        start = -1
        for keyword in ('"task_id"', '"artifacts"'):
            idx = response_text.find(keyword)
            if idx >= 0:
                # Walk backwards to find the opening brace
                for i in range(idx, -1, -1):
                    if response_text[i] == '{':
                        start = i
                        break
                if start >= 0:
                    break

        if start >= 0:
            # Find matching closing brace
            depth = 0
            for i in range(start, len(response_text)):
                if response_text[i] == '{':
                    depth += 1
                elif response_text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = response_text[start:i + 1]
                        data = json.loads(candidate)
                        if isinstance(data, dict):
                            data.setdefault("task_id", task_id)
                            return BuilderOutputManifest.from_dict(data)
                        break
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 3: Fallback — minimal manifest
    return BuilderOutputManifest(
        task_id=task_id,
        artifacts=[],
        incomplete=[],
        questions_for_architect=[],
    )


def extract_code_artifacts(response_text: str) -> list[tuple[str, str]]:
    """Find `# File: path` + code blocks, return (filepath, content) pairs."""
    artifacts: list[tuple[str, str]] = []

    # Pattern: # File: path/to/file.ext followed by a code block
    pattern = re.compile(
        r"#\s*File:\s*(.+?)\s*\n"
        r"```\w*\s*\n"
        r"(.*?)"
        r"```",
        re.DOTALL,
    )

    for match in pattern.finditer(response_text):
        filepath = match.group(1).strip()
        content = match.group(2)
        artifacts.append((filepath, content))

    return artifacts


def save_artifacts(
    artifacts: list[tuple[str, str]],
    project_id: str,
    task_id: str,
    projects_dir: str | Path,
) -> list[Path]:
    """Write code artifacts to projects/{id}/artifacts/{task_id}/."""
    base_dir = Path(projects_dir) / project_id / "artifacts" / task_id
    base_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for filepath, content in artifacts:
        # Preserve the file's relative path structure
        full_path = base_dir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        paths.append(full_path)

    return paths


def save_builder_manifest(
    manifest: BuilderOutputManifest,
    project_id: str,
    projects_dir: str | Path,
) -> Path:
    """Write manifest to projects/{id}/builder_outputs/{task_id}.json."""
    output_dir = Path(projects_dir) / project_id / "builder_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / f"{manifest.task_id}.json"
    path.write_text(manifest.to_json(), encoding="utf-8")
    return path


def load_builder_manifest(
    task_id: str,
    project_id: str,
    projects_dir: str | Path,
) -> BuilderOutputManifest:
    """Load manifest from projects/{id}/builder_outputs/{task_id}.json."""
    path = Path(projects_dir) / project_id / "builder_outputs" / f"{task_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Builder manifest not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return BuilderOutputManifest.from_dict(data)
