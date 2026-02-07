"""Review Engine — three-stage review pipeline for builder output validation.

Doc 08 §4: Validates all builder output before it enters the project permanently.

Stages:
1. Automated constitutional checks (fast, rule-based, no AI)
2. Architect AI review (semantic check via NexusConnector)
3. Integration checks (cross-task consistency)

If Stage 1 has critical failures, Stages 2-3 are skipped (no AI tokens wasted).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestration.models import (
    Artifact,
    BuilderOutputManifest,
    BuilderTaskContract,
    CheckResult,
    ReviewResult,
    ReviewVerdict,
)
from orchestration.project_state import ProjectState, generate_id


# ---------------------------------------------------------------------------
# Connector protocol (reuse pattern from architect.py / builder_dispatch.py)
# ---------------------------------------------------------------------------

class ConnectorProtocol(Protocol):
    conversation_history: list
    session_id: str

    async def send_message(self, message: str, **kwargs: Any) -> dict[str, Any]: ...


ConnectorFactory = Callable[..., ConnectorProtocol]


# ---------------------------------------------------------------------------
# Stage 1 — Automated checks (pure functions, no AI)
# ---------------------------------------------------------------------------

def check_manifest_completeness(manifest: BuilderOutputManifest) -> CheckResult:
    """Check that manifest has task_id and non-empty artifacts."""
    if not manifest.task_id:
        return CheckResult(
            check_name="manifest_completeness",
            passed=False,
            message="Manifest missing task_id.",
        )
    if not manifest.artifacts:
        return CheckResult(
            check_name="manifest_completeness",
            passed=False,
            message="Manifest has no artifacts.",
        )
    return CheckResult(
        check_name="manifest_completeness",
        passed=True,
        message="Manifest is complete.",
    )


def check_scope_compliance(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> CheckResult:
    """No artifact file paths should overlap with scope_must_not_touch areas."""
    if not task.scope_must_not_touch:
        return CheckResult(
            check_name="scope_compliance",
            passed=True,
            message="No scope restrictions defined.",
        )

    violations = []
    for art in manifest.artifacts:
        file_path = art.get("file", "") if isinstance(art, dict) else ""
        for boundary in task.scope_must_not_touch:
            if boundary.lower() in file_path.lower():
                violations.append(f"Artifact '{file_path}' touches restricted area '{boundary}'")

    if violations:
        return CheckResult(
            check_name="scope_compliance",
            passed=False,
            message="; ".join(violations),
        )
    return CheckResult(
        check_name="scope_compliance",
        passed=True,
        message="All artifacts within allowed scope.",
    )


def check_test_coverage(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> CheckResult:
    """If test_criteria exist, at least one artifact path contains 'test'."""
    if not task.test_criteria:
        return CheckResult(
            check_name="test_coverage",
            passed=True,
            message="No test criteria defined; auto-pass.",
        )

    has_test = False
    for art in manifest.artifacts:
        file_path = art.get("file", "") if isinstance(art, dict) else ""
        if "test" in file_path.lower():
            has_test = True
            break

    if not has_test:
        return CheckResult(
            check_name="test_coverage",
            passed=False,
            message="Task has test criteria but no test artifacts found.",
        )
    return CheckResult(
        check_name="test_coverage",
        passed=True,
        message="Test artifacts present.",
    )


def check_constraint_presence(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> CheckResult:
    """If constraints_to_enforce exist, check artifact fields reference them.

    Soft check — returns warning message but still passes (not a hard fail).
    """
    if not task.constraints_to_enforce:
        return CheckResult(
            check_name="constraint_presence",
            passed=True,
            message="No constraints to enforce.",
        )

    # Collect all constraints_enforced from artifacts
    enforced = set()
    for art in manifest.artifacts:
        if isinstance(art, dict):
            for c in art.get("constraints_enforced", []):
                enforced.add(c.lower())
            # Also check implements field for constraint references
            impl = art.get("implements", "").lower()
            for constraint in task.constraints_to_enforce:
                if constraint.lower() in impl:
                    enforced.add(constraint.lower())

    missing = []
    for constraint in task.constraints_to_enforce:
        found = False
        for e in enforced:
            if constraint.lower() in e or e in constraint.lower():
                found = True
                break
        if not found:
            missing.append(constraint)

    if missing:
        return CheckResult(
            check_name="constraint_presence",
            passed=True,  # Soft check — warning, not fail
            message=f"Warning: constraints not explicitly referenced: {', '.join(missing)}",
        )
    return CheckResult(
        check_name="constraint_presence",
        passed=True,
        message="All constraints referenced in artifacts.",
    )


def check_incomplete_items(manifest: BuilderOutputManifest) -> CheckResult:
    """Fails if manifest.incomplete is non-empty."""
    if manifest.incomplete:
        items = [
            item.get("item", str(item)) if isinstance(item, dict) else str(item)
            for item in manifest.incomplete
        ]
        return CheckResult(
            check_name="incomplete_items",
            passed=False,
            message=f"Incomplete items: {', '.join(items)}",
        )
    return CheckResult(
        check_name="incomplete_items",
        passed=True,
        message="No incomplete items.",
    )


def run_automated_checks(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> list[CheckResult]:
    """Run all Stage 1 automated checks. Returns list of CheckResults."""
    return [
        check_manifest_completeness(manifest),
        check_scope_compliance(manifest, task),
        check_test_coverage(manifest, task),
        check_constraint_presence(manifest, task),
        check_incomplete_items(manifest),
    ]


# ---------------------------------------------------------------------------
# Stage 3 — Integration checks (pure functions, no AI)
# ---------------------------------------------------------------------------

def check_interface_matching(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> list[str]:
    """If interfaces_produces declared but no artifacts, flag it."""
    issues = []
    if task.interfaces_produces and not manifest.artifacts:
        issues.append(
            f"Task declares interfaces_produces ({', '.join(task.interfaces_produces)}) "
            f"but has no artifacts."
        )
    return issues


def check_dependency_satisfaction(
    task: BuilderTaskContract, project: ProjectState
) -> list[str]:
    """All depends_on task IDs must be in completed_tasks."""
    issues = []
    completed_ids = {t.task_id for t in project.completed_tasks}
    for dep_id in task.depends_on:
        if dep_id not in completed_ids:
            issues.append(f"Dependency '{dep_id}' not in completed tasks.")
    return issues


def check_duplicate_artifacts(
    manifest: BuilderOutputManifest,
    all_manifests: list[BuilderOutputManifest],
) -> list[str]:
    """No file path should appear in multiple manifests."""
    issues = []
    my_files = set()
    for art in manifest.artifacts:
        file_path = art.get("file", "") if isinstance(art, dict) else ""
        if file_path:
            my_files.add(file_path)

    for other in all_manifests:
        if other.task_id == manifest.task_id:
            continue
        for art in other.artifacts:
            file_path = art.get("file", "") if isinstance(art, dict) else ""
            if file_path in my_files:
                issues.append(
                    f"Artifact '{file_path}' also appears in task {other.task_id}."
                )
    return issues


def run_integration_check(
    manifest: BuilderOutputManifest,
    task: BuilderTaskContract,
    project: ProjectState,
    all_manifests: list[BuilderOutputManifest],
) -> list[str]:
    """Run all Stage 3 integration checks. Returns list of issue strings."""
    issues = []
    issues.extend(check_interface_matching(manifest, task))
    issues.extend(check_dependency_satisfaction(task, project))
    issues.extend(check_duplicate_artifacts(manifest, all_manifests))
    return issues


# ---------------------------------------------------------------------------
# Review response parsing (Stage 2 helpers)
# ---------------------------------------------------------------------------

def _build_review_prompt(
    manifest: BuilderOutputManifest, task: BuilderTaskContract
) -> str:
    """Format task contract summary + manifest for the reviewer AI."""
    artifact_lines = []
    for art in manifest.artifacts:
        if isinstance(art, dict):
            artifact_lines.append(
                f"  - {art.get('file', '?')}: {art.get('implements', 'no description')}"
            )

    return (
        "REVIEW REQUEST\n"
        "==============\n"
        f"Task ID: {task.task_id}\n"
        f"Task Name: {task.task_name}\n"
        f"Objective: {task.objective}\n"
        f"Subsystem: {task.subsystem}\n"
        f"Task Type: {task.task_type}\n\n"
        "Must Build:\n"
        + "\n".join(f"  - {item}" for item in task.scope_must_build)
        + "\n\nMust NOT Touch:\n"
        + "\n".join(f"  - {item}" for item in task.scope_must_not_touch)
        + "\n\nTest Criteria:\n"
        + "\n".join(f"  - {tc}" for tc in task.test_criteria)
        + "\n\nBuilder Output Manifest:\n"
        f"  Artifacts ({len(manifest.artifacts)}):\n"
        + "\n".join(artifact_lines)
        + "\n\n"
        + (f"  Incomplete: {len(manifest.incomplete)} items\n" if manifest.incomplete else "")
        + (f"  Questions: {len(manifest.questions_for_architect)}\n" if manifest.questions_for_architect else "")
        + "\nReview this builder output against the task contract.\n"
        "Check:\n"
        "1. Does the output fulfill the objective?\n"
        "2. Are all must-build items addressed?\n"
        "3. Is the quality acceptable?\n"
        "4. Any concerns about the implementation approach?\n\n"
        "End your response with exactly one line:\n"
        "VERDICT: accept|reject|revise|escalate\n"
    )


def _parse_review_response(response_text: str) -> tuple[str, str]:
    """Extract VERDICT and notes from reviewer response.

    Returns (notes, verdict). Defaults to 'accept' if no verdict found.
    """
    verdict = "accept"
    notes = response_text

    # Look for VERDICT: line
    match = re.search(r"VERDICT:\s*(accept|reject|revise|escalate)", response_text, re.IGNORECASE)
    if match:
        verdict = match.group(1).lower()
        # Notes = everything before the verdict line
        verdict_pos = match.start()
        notes = response_text[:verdict_pos].strip()

    return notes, verdict


# ---------------------------------------------------------------------------
# Verdict composition
# ---------------------------------------------------------------------------

def compose_verdict(
    checks: list[CheckResult],
    notes: str,
    suggestion: str,
    issues: list[str],
) -> str:
    """Compose final verdict from all three stages.

    Priority:
    - Automated fail → REJECT
    - Architect reject → REJECT
    - Architect revise or integration issues → REVISE
    - Architect escalate → ESCALATE
    - Else → ACCEPT
    """
    # Stage 1: any critical failures?
    for check in checks:
        if not check.passed:
            return ReviewVerdict.REJECT.value

    # Stage 2: architect verdict
    if suggestion == "reject":
        return ReviewVerdict.REJECT.value
    if suggestion == "escalate":
        return ReviewVerdict.ESCALATE.value
    if suggestion == "revise":
        return ReviewVerdict.REVISE.value

    # Stage 3: integration issues
    if issues:
        return ReviewVerdict.REVISE.value

    return ReviewVerdict.ACCEPT.value


# ---------------------------------------------------------------------------
# Review persistence
# ---------------------------------------------------------------------------

def save_review_result(
    result: ReviewResult,
    project_id: str,
    projects_dir: str | Path,
) -> Path:
    """Write review result to projects/{id}/reviews/{review_id}.json."""
    reviews_dir = Path(projects_dir) / project_id / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    path = reviews_dir / f"{result.review_id}.json"
    path.write_text(result.to_json(), encoding="utf-8")
    return path


def load_review_results(
    project_id: str,
    projects_dir: str | Path,
) -> list[ReviewResult]:
    """Load all review results from projects/{id}/reviews/."""
    reviews_dir = Path(projects_dir) / project_id / "reviews"
    if not reviews_dir.exists():
        return []

    results = []
    for path in sorted(reviews_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        results.append(ReviewResult.from_dict(data))
    return results


# ---------------------------------------------------------------------------
# ReviewEngine — orchestrates the 3-stage pipeline
# ---------------------------------------------------------------------------

class ReviewEngine:
    """Orchestrates the three-stage review pipeline for builder output."""

    def __init__(
        self,
        project: ProjectState,
        projects_dir: str | Path,
        constitution,
        connector_factory: ConnectorFactory,
        role_config: dict,
    ):
        self.project = project
        self.projects_dir = Path(projects_dir)
        self.constitution = constitution
        self.connector_factory = connector_factory
        self.role_config = role_config

    async def review_task(
        self,
        manifest: BuilderOutputManifest,
        task: BuilderTaskContract,
        all_manifests: list[BuilderOutputManifest],
    ) -> ReviewResult:
        """Run all 3 stages for one task.

        If Stage 1 has critical failures, skips Stages 2-3 and returns REJECT.
        """
        review_id = generate_id("review")

        # Stage 1: automated checks
        checks = run_automated_checks(manifest, task)
        has_critical_failure = any(not c.passed for c in checks)

        notes = ""
        suggestion = "accept"
        issues: list[str] = []

        if not has_critical_failure:
            # Stage 2: architect AI review
            notes, suggestion = await self.run_architect_review(manifest, task)

            # Stage 3: integration checks
            issues = run_integration_check(
                manifest, task, self.project, all_manifests
            )

        # Compose final verdict
        verdict = compose_verdict(checks, notes, suggestion, issues)

        result = ReviewResult(
            review_id=review_id,
            task_id=task.task_id,
            verdict=verdict,
            automated_checks=[c.to_dict() for c in checks],
            architect_notes=notes,
            integration_issues=issues,
            revision_instructions=notes if verdict == ReviewVerdict.REVISE.value else None,
            escalation_reason=notes if verdict == ReviewVerdict.ESCALATE.value else None,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )

        # Save to disk
        save_review_result(result, self.project.project_id, self.projects_dir)

        return result

    async def run_architect_review(
        self,
        manifest: BuilderOutputManifest,
        task: BuilderTaskContract,
    ) -> tuple[str, str]:
        """Stage 2: Create reviewer connector, send review prompt, parse verdict.

        Returns (notes, verdict_suggestion).
        """
        # Build reviewer system prompt from constitution (VALIDATION phase context)
        system_prompt = self.constitution.build_architect_context(self.project)

        connector = self.connector_factory(
            provider=self.role_config.get("provider", "anthropic"),
            model=self.role_config.get("model", "claude-sonnet-4-5-20250929"),
            system_prompt=system_prompt,
        )

        prompt = _build_review_prompt(manifest, task)
        response = await connector.send_message(prompt)
        content = response.get("content", "")

        notes, verdict = _parse_review_response(content)
        return notes, verdict

    async def review_all(self) -> list[ReviewResult]:
        """Review all completed tasks.

        Loads manifests from disk, matches to completed_tasks,
        skips already-reviewed tasks, returns all results.
        """
        from orchestration.builder_dispatch import load_builder_manifest

        # Load existing reviews to skip already-reviewed tasks
        existing_reviews = load_review_results(
            self.project.project_id, self.projects_dir
        )
        reviewed_task_ids = {r.task_id for r in existing_reviews}

        # Load all manifests for completed tasks
        all_manifests: list[BuilderOutputManifest] = []
        tasks_to_review: list[tuple[BuilderOutputManifest, BuilderTaskContract]] = []

        for task in self.project.completed_tasks:
            try:
                manifest = load_builder_manifest(
                    task.task_id, self.project.project_id, self.projects_dir
                )
                all_manifests.append(manifest)
                if task.task_id not in reviewed_task_ids:
                    tasks_to_review.append((manifest, task))
            except FileNotFoundError:
                # Task has no manifest — skip
                continue

        results: list[ReviewResult] = list(existing_reviews)

        for manifest, task in tasks_to_review:
            result = await self.review_task(manifest, task, all_manifests)
            results.append(result)

        return results
