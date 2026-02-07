"""Task Decomposer — breaks Architecture Template into Builder Task Contracts.

Doc 07 Phase 4 (Build Decomposition): Takes the architecture template produced
by Phases 2-3 and decomposes it into scoped, ordered builder tasks.

Flow:
1. Prompt Architect with architecture_template + decomposition instructions
2. Parse response into BuilderTaskContract objects
3. Resolve dependencies (topological sort via Kahn's algorithm)
4. Assign providers based on task complexity
5. Produce cost estimate
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from orchestration.models import (
    BuilderTaskContract,
    TaskType,
    TierCostEstimate,
)
from orchestration.project_state import generate_id


# ---------------------------------------------------------------------------
# Provider assignment: TaskType → role tier
# ---------------------------------------------------------------------------

# Complex tasks require stronger models; simple tasks use cost-efficient ones
_COMPLEX_TASK_TYPES = {
    TaskType.STATE_SCHEMA.value,
    TaskType.FLOW.value,
    TaskType.CONSTRAINT.value,
    TaskType.FAILURE_RECOVERY.value,
    TaskType.DEPENDENCY_CASCADE.value,
}

_SIMPLE_TASK_TYPES = {
    TaskType.GENERAL.value,
    TaskType.UX_LAYER.value,
}


# ---------------------------------------------------------------------------
# Decomposition prompt
# ---------------------------------------------------------------------------

DECOMPOSITION_PROMPT = """\
Now proceed to Phase 4 — Build Decomposition.

Break the Architecture Template into individual Builder Task Contracts. Each task \
must be a scoped, atomic unit of work that a single builder can complete independently.

For each task, use this EXACT format:

TASK [N]: "[task name]"

  Subsystem: [subsystem name]
  Task type: [state_schema | flow | constraint | failure_recovery | dependency_cascade | ux_layer | general]
  Objective: [What this task must accomplish]

  Inputs:
    - [input 1]
    - [input 2]

  Must build:
    - [deliverable 1]
    - [deliverable 2]

  Must not touch:
    - [boundary 1]

  Rules to implement:
    - [rule 1]

  Constraints to enforce:
    - [constraint 1]

  Interfaces receives:
    - [interface input]

  Interfaces produces:
    - [interface output]

  Test criteria:
    - [test 1]
    - [test 2]

  Depends on: [comma-separated task numbers, or "none"]

Requirements:
- Order tasks so dependencies come first
- Use "Depends on: none" for tasks with no dependencies
- Mark task types accurately — this determines which provider handles them
- Keep each task scoped to one subsystem
- Include test criteria for every task
- Aim for 5-20 tasks depending on project complexity

After the task list, provide a cost estimate:

COST ESTIMATE:
  Task count: [N]
  Complex tasks: [count] (state_schema, flow, constraint, failure_recovery, dependency_cascade)
  Simple tasks: [count] (general, ux_layer)
  Cost drivers:
    - [driver 1]
  Savings opportunities:
    - [opportunity 1]
"""


# ---------------------------------------------------------------------------
# TaskDecomposer
# ---------------------------------------------------------------------------

class TaskDecomposer:
    """Decomposes an Architecture Template into ordered Builder Task Contracts."""

    async def decompose(
        self,
        connector,
        project,
        roles_config: dict | None = None,
    ) -> tuple[list[BuilderTaskContract], TierCostEstimate]:
        """Run AI-driven decomposition.

        Args:
            connector: Active NexusConnector/mock with conversation context.
            project: Current ProjectState (has architecture_template).
            roles_config: Provider config from config/roles.json.

        Returns:
            (tasks, cost_estimate) — ordered task list and cost estimate.
        """
        prompt = DECOMPOSITION_PROMPT
        response = await connector.send_message(prompt)
        content = response.get("content", "")

        tasks = _parse_task_contracts(content)

        # Assign unique IDs
        for task in tasks:
            task.task_id = generate_id("task")
            task.build_tier = project.current_tier
            task.created_at = datetime.now(timezone.utc).isoformat()

        # Resolve dependencies and assign parallel groups
        tasks = _resolve_dependencies(tasks)

        # Assign providers
        tasks = _assign_providers(tasks, roles_config or {})

        # Estimate cost
        cost = _estimate_cost(tasks, roles_config or {})

        return tasks, cost


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_task_contracts(text: str) -> list[BuilderTaskContract]:
    """Parse TASK [N]: "name" blocks from AI response text."""
    tasks: list[BuilderTaskContract] = []
    lines = text.splitlines()
    current_task: dict | None = None
    # Track original task number for dependency resolution
    task_number_map: dict[int, int] = {}  # task_number -> index in tasks list

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect task header: TASK 1: "Name" or TASK [1]: "Name"
        task_match = re.match(
            r'^TASK\s+\[?(\d+)\]?:\s*["\u201c](.+?)["\u201d]', line
        )
        if task_match:
            # Save previous task
            if current_task:
                tasks.append(_build_task_contract(current_task))
                task_number_map[current_task["number"]] = len(tasks) - 1

            task_number = int(task_match.group(1))
            task_name = task_match.group(2)
            current_task = {
                "number": task_number,
                "task_name": task_name,
                "lines": [],
            }
        elif current_task is not None:
            current_task["lines"].append(line)

        i += 1

    # Save last task
    if current_task:
        tasks.append(_build_task_contract(current_task))
        task_number_map[current_task["number"]] = len(tasks) - 1

    # Resolve "Depends on" references (task numbers → placeholder names)
    # After IDs are assigned upstream, the dependency names will be replaced
    for task in tasks:
        resolved_deps = []
        for dep in task.depends_on:
            dep = dep.strip()
            # Try to parse as task number
            dep_nums = re.findall(r'\d+', dep)
            for num_str in dep_nums:
                num = int(num_str)
                if num in task_number_map:
                    idx = task_number_map[num]
                    resolved_deps.append(f"__task_index_{idx}")
            if not dep_nums and dep.lower() != "none":
                resolved_deps.append(dep)
        task.depends_on = resolved_deps

    return tasks


def _build_task_contract(data: dict) -> BuilderTaskContract:
    """Build a BuilderTaskContract from parsed task data."""
    lines = data.get("lines", [])
    text = "\n".join(lines)

    task = BuilderTaskContract(
        task_name=data["task_name"],
    )

    task.subsystem = _extract_simple_field(text, "Subsystem")
    task.objective = _extract_simple_field(text, "Objective")

    # Task type
    raw_type = _extract_simple_field(text, "Task type").lower().strip()
    valid_types = {t.value for t in TaskType}
    if raw_type in valid_types:
        task.task_type = raw_type
    else:
        task.task_type = TaskType.GENERAL.value

    task.inputs = _extract_bullet_list(text, "Inputs")
    task.scope_must_build = _extract_bullet_list(text, "Must build")
    task.scope_must_not_touch = _extract_bullet_list(text, "Must not touch")
    task.rules_to_implement = _extract_bullet_list(text, "Rules to implement")
    task.constraints_to_enforce = _extract_bullet_list(text, "Constraints to enforce")
    task.interfaces_receives = _extract_bullet_list(text, "Interfaces receives")
    task.interfaces_produces = _extract_bullet_list(text, "Interfaces produces")
    task.test_criteria = _extract_bullet_list(text, "Test criteria")

    # Dependencies — raw, will be resolved later
    deps_str = _extract_simple_field(text, "Depends on")
    if deps_str and deps_str.lower().strip() != "none":
        task.depends_on = [d.strip() for d in deps_str.split(",") if d.strip()]
    else:
        task.depends_on = []

    return task


def _extract_simple_field(text: str, field_name: str) -> str:
    """Extract a single-line field like 'Subsystem: X'."""
    pattern = rf"(?:^|\n)\s*{re.escape(field_name)}:\s*(.+?)(?:\n|$)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _extract_bullet_list(text: str, section_name: str) -> list[str]:
    """Extract a bulleted list under a section heading."""
    pattern = rf"{re.escape(section_name)}:\s*\n((?:\s*[-*]\s+.+\n?)+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        bullets_text = match.group(1)
        return [
            line.strip().lstrip("-* ").strip()
            for line in bullets_text.splitlines()
            if line.strip().startswith(("-", "*"))
        ]
    return []


# ---------------------------------------------------------------------------
# Dependency resolution — Kahn's algorithm
# ---------------------------------------------------------------------------

class CyclicDependencyError(Exception):
    """Raised when task dependencies contain a cycle."""
    pass


def _resolve_dependencies(tasks: list[BuilderTaskContract]) -> list[BuilderTaskContract]:
    """Topological sort via Kahn's algorithm. Assigns parallel_group to each task.

    Dependencies referencing __task_index_N are resolved to actual task IDs.
    Detects cycles and raises CyclicDependencyError.
    """
    n = len(tasks)

    # Replace __task_index_N placeholders with actual task IDs
    for task in tasks:
        resolved = []
        for dep in task.depends_on:
            match = re.match(r"__task_index_(\d+)", dep)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < n:
                    resolved.append(tasks[idx].task_id)
            else:
                resolved.append(dep)
        task.depends_on = resolved

    # Build adjacency for topological sort
    task_id_to_idx = {t.task_id: i for i, t in enumerate(tasks)}
    in_degree = [0] * n
    dependents: dict[int, list[int]] = defaultdict(list)  # idx -> list of idx that depend on it

    for i, task in enumerate(tasks):
        for dep_id in task.depends_on:
            if dep_id in task_id_to_idx:
                dep_idx = task_id_to_idx[dep_id]
                dependents[dep_idx].append(i)
                in_degree[i] += 1

    # Kahn's algorithm
    queue = deque()
    for i in range(n):
        if in_degree[i] == 0:
            queue.append(i)

    sorted_indices: list[int] = []
    group_assignments: dict[int, int] = {}
    current_group = 0

    # Process level by level for parallel group assignment
    while queue:
        level_size = len(queue)
        level_indices = []
        for _ in range(level_size):
            idx = queue.popleft()
            sorted_indices.append(idx)
            level_indices.append(idx)
            group_assignments[idx] = current_group

        # Decrease in_degree for dependents
        for idx in level_indices:
            for dep_idx in dependents[idx]:
                in_degree[dep_idx] -= 1
                if in_degree[dep_idx] == 0:
                    queue.append(dep_idx)

        current_group += 1

    if len(sorted_indices) != n:
        raise CyclicDependencyError(
            f"Cyclic dependency detected: processed {len(sorted_indices)} of {n} tasks"
        )

    # Assign parallel groups
    for idx, group in group_assignments.items():
        tasks[idx].parallel_group = group

    # Return in topological order
    return [tasks[i] for i in sorted_indices]


# ---------------------------------------------------------------------------
# Provider assignment
# ---------------------------------------------------------------------------

def _assign_providers(
    tasks: list[BuilderTaskContract],
    roles_config: dict,
) -> list[BuilderTaskContract]:
    """Assign provider recommendations based on task type complexity."""
    for task in tasks:
        if task.task_type in _COMPLEX_TASK_TYPES:
            role = "builder_complex"
        else:
            role = "builder_simple"

        role_cfg = roles_config.get(role, {})
        provider = role_cfg.get("provider", "")
        model = role_cfg.get("model", "")
        if provider and model:
            task.assigned_provider = f"{provider}/{model}"
        elif provider:
            task.assigned_provider = provider
        else:
            task.assigned_provider = role

    return tasks


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

# Rough token estimates per task type (input + output)
_TOKEN_ESTIMATES = {
    "complex": {"input": 8000, "output": 4000},
    "simple": {"input": 4000, "output": 2000},
}

# Cost per million tokens (rough averages)
_COST_PER_M_TOKENS = {
    "builder_complex": {"input": 3.0, "output": 15.0},
    "builder_simple": {"input": 0.27, "output": 1.10},
}


def _estimate_cost(
    tasks: list[BuilderTaskContract],
    roles_config: dict,
) -> TierCostEstimate:
    """Estimate build cost from task list."""
    complex_count = sum(1 for t in tasks if t.task_type in _COMPLEX_TASK_TYPES)
    simple_count = len(tasks) - complex_count

    provider_mix = {}
    for task in tasks:
        provider = task.assigned_provider or "unknown"
        provider_mix[provider] = provider_mix.get(provider, 0) + 1

    # Calculate token costs
    complex_input = complex_count * _TOKEN_ESTIMATES["complex"]["input"]
    complex_output = complex_count * _TOKEN_ESTIMATES["complex"]["output"]
    simple_input = simple_count * _TOKEN_ESTIMATES["simple"]["input"]
    simple_output = simple_count * _TOKEN_ESTIMATES["simple"]["output"]

    complex_cost = (
        (complex_input / 1_000_000) * _COST_PER_M_TOKENS["builder_complex"]["input"]
        + (complex_output / 1_000_000) * _COST_PER_M_TOKENS["builder_complex"]["output"]
    )
    simple_cost = (
        (simple_input / 1_000_000) * _COST_PER_M_TOKENS["builder_simple"]["input"]
        + (simple_output / 1_000_000) * _COST_PER_M_TOKENS["builder_simple"]["output"]
    )

    mid = complex_cost + simple_cost
    low = mid * 0.6
    high = mid * 1.8

    cost_drivers = []
    if complex_count > 0:
        cost_drivers.append(f"{complex_count} complex tasks using higher-tier provider")
    if simple_count > 0:
        cost_drivers.append(f"{simple_count} simple tasks using cost-efficient provider")

    savings = []
    if complex_count > 2:
        savings.append("Consider if any complex tasks can be simplified to use cheaper provider")
    if simple_count > 5:
        savings.append("Batch simple tasks where possible to reduce overhead")

    return TierCostEstimate(
        task_count=len(tasks),
        provider_mix=provider_mix,
        cost_low=round(low, 4),
        cost_mid=round(mid, 4),
        cost_high=round(high, 4),
        cost_drivers=cost_drivers,
        savings_opportunities=savings,
    )


# ---------------------------------------------------------------------------
# Task persistence
# ---------------------------------------------------------------------------

def save_task_contracts(
    tasks: list[BuilderTaskContract],
    project_id: str,
    projects_dir: str | Path,
) -> list[Path]:
    """Save each task as projects/{id}/tasks/{task_id}.json."""
    tasks_dir = Path(projects_dir) / project_id / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for task in tasks:
        path = tasks_dir / f"{task.task_id}.json"
        path.write_text(task.to_json(), encoding="utf-8")
        paths.append(path)

    return paths


def load_task_contracts(
    project_id: str,
    projects_dir: str | Path,
) -> list[BuilderTaskContract]:
    """Load all task contracts from projects/{id}/tasks/."""
    tasks_dir = Path(projects_dir) / project_id / "tasks"
    if not tasks_dir.exists():
        return []

    tasks = []
    for path in sorted(tasks_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks.append(BuilderTaskContract.from_dict(data))

    return tasks
