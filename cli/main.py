"""CLI entry point for Nexus Orchestrator.

Tier 1 commands:
  nexus-orch new --vision <path>       Create a new project from a Vision Contract
  nexus-orch status --project <id>     Show project status

Tier 2 commands:
  nexus-orch architect --project <id>  Start or continue Architect session
  nexus-orch approve --project <id> --gate <gate_id> [--choice X] [--modify/--combine/--revise/--redirect]
  nexus-orch reject --project <id> --gate <gate_id> --feedback "reason"
  nexus-orch gates --project <id>      List all gates and their status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from orchestration.models import (
    GateResponse,
    GateResponseType,
    GateStatus,
    VisionContract,
    VisionValidationError,
)
from orchestration.project_state import ProjectState

# Default paths (relative to working directory)
DEFAULT_PROJECTS_DIR = "projects"
DEFAULT_DOCS_DIR = "constitutional_docs"


def cmd_new(args: argparse.Namespace) -> int:
    """Create a new project from a Vision Contract markdown file."""
    vision_path = Path(args.vision)
    if not vision_path.exists():
        print(f"Error: Vision contract not found at {vision_path}", file=sys.stderr)
        return 1

    raw_md = vision_path.read_text(encoding="utf-8")
    strict = not getattr(args, "relaxed", False)

    try:
        vision = VisionContract.from_markdown(raw_md, strict=strict)
    except VisionValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not vision.project_name:
        # Derive from filename if not set in markdown
        vision.project_name = vision_path.stem.replace("_", " ").replace("-", " ").title()

    project = ProjectState(
        project_name=vision.project_name,
        vision_contract=vision,
        current_tier=0,
        current_phase="vision_intake",
    )

    projects_dir = Path(args.projects_dir)
    state_path = project.save(projects_dir)
    project_dir = state_path.parent

    # Show warnings for missing recommended fields (strict mode only)
    if strict:
        try:
            warnings = vision.validate()
        except VisionValidationError:
            pass  # Already validated above — should not reach here
        else:
            for w in warnings:
                print(f"  Warning: missing recommended field — {w}", file=sys.stderr)

    print(f"Project created: {project.project_name}")
    print(f"  ID:       {project.project_id}")
    print(f"  State:    {state_path}")
    print(f"  Dir:      {project_dir}")
    print(f"  Phase:    {project.current_phase}")
    print(f"  Tier:     {project.current_tier}")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show project status."""
    projects_dir = Path(args.projects_dir)
    project_id = args.project

    # If no project ID given, list all projects
    if not project_id:
        ids = ProjectState.list_projects(projects_dir)
        if not ids:
            print("No projects found.")
            return 0
        print("Projects:")
        for pid in ids:
            try:
                p = ProjectState.load(pid, projects_dir)
                print(f"  {pid}  {p.project_name}  tier={p.current_tier}  phase={p.current_phase}")
            except Exception as e:
                print(f"  {pid}  (error loading: {e})")
        return 0

    # Load and display specific project
    try:
        project = ProjectState.load(project_id, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{project_id}' not found in {projects_dir}", file=sys.stderr)
        return 1

    print(project.status_summary())
    return 0


# ---------------------------------------------------------------------------
# Tier 2 — Architect session commands
# ---------------------------------------------------------------------------

def _load_role_config(role: str, docs_dir: str = DEFAULT_DOCS_DIR) -> dict:
    """Load role config from config/roles.json."""
    config_path = Path(docs_dir).parent / "config" / "roles.json"
    if not config_path.exists():
        # Fallback: try relative to cwd
        config_path = Path("config") / "roles.json"
    if config_path.exists():
        roles = json.loads(config_path.read_text(encoding="utf-8"))
        return roles.get(role, {})
    return {}


def cmd_architect(args: argparse.Namespace) -> int:
    """Start or continue an Architect session."""
    from orchestration.architect import ArchitectSession, default_connector_factory
    from orchestration.constitution import ConstitutionEnforcer
    from orchestration.gate_manager import GateManager

    projects_dir = Path(args.projects_dir)
    docs_dir = Path(args.docs_dir)

    try:
        project = ProjectState.load(args.project, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{args.project}' not found", file=sys.stderr)
        return 1

    # If there's a pending gate, tell the user to respond first
    if project.pending_gate:
        _print_gate_detail(project.pending_gate)
        print("\nUse 'approve' or 'reject' to respond before continuing.")
        return 0

    constitution = ConstitutionEnforcer(docs_dir)
    gate_manager = GateManager(projects_dir)
    role_config = _load_role_config("architect", str(docs_dir))

    session = ArchitectSession(
        project=project,
        projects_dir=projects_dir,
        constitution=constitution,
        gate_manager=gate_manager,
        role_config=role_config,
    )

    return asyncio.run(_run_architect_phase(session, project))


async def _run_architect_phase(session, project) -> int:
    """Run the appropriate Architect phase based on project state."""
    from orchestration.models import GateType

    phase = project.current_phase

    if phase == "vision_intake":
        # Check if vision gate already exists (and was resolved)
        vision_gates = [g for g in project.gates if g.gate_type == GateType.VISION_CONFIRMED.value]
        resolved = [g for g in vision_gates if g.status != GateStatus.PENDING.value]

        if not vision_gates:
            print("Starting Architect session — Vision Intake...")
            gate = await session.run_vision_intake()
            _print_gate_detail(gate)
            return 0
        elif resolved:
            print("Processing vision response, advancing to System Design...")
            await session.process_vision_response(resolved[-1])
            gate = await session.run_system_design()
            _print_gate_detail(gate)
            return 0

    elif phase == "system_design":
        design_gates = [g for g in project.gates if g.gate_type == GateType.SYSTEM_DESIGN.value]
        resolved = [g for g in design_gates if g.status != GateStatus.PENDING.value]

        if not design_gates:
            print("Running System Design phase...")
            gate = await session.run_system_design()
            _print_gate_detail(gate)
            return 0
        elif resolved:
            print("Processing design choice, producing Architecture Template...")
            content = await session.process_design_response(resolved[-1])
            print("\nArchitecture Template produced.")
            if content:
                preview = content[:800] + ("..." if len(content) > 800 else "")
                print(preview)
            return 0

    elif phase == "detailed_design":
        # Check if there's already a decomposition gate
        decomp_gates = [g for g in project.gates if g.gate_type == GateType.BUILD_DECOMPOSITION.value]
        if not decomp_gates:
            print("Running Build Decomposition phase...")
            gate = await session.run_build_decomposition()
            _print_gate_detail(gate)
            return 0
        else:
            resolved = [g for g in decomp_gates if g.status != GateStatus.PENDING.value]
            if resolved:
                print("Processing decomposition response, storing task queue...")
                tasks = await session.process_decomposition_response(resolved[-1])
                print(f"\n{len(tasks)} tasks queued for build supervision.")
                for t in tasks:
                    dep_str = f" (deps: {', '.join(t.depends_on)})" if t.depends_on else ""
                    print(f"  [Group {t.parallel_group}] {t.task_name} ({t.task_type}){dep_str}")
                return 0

    elif phase == "build_decomposition":
        decomp_gates = [g for g in project.gates if g.gate_type == GateType.BUILD_DECOMPOSITION.value]
        resolved = [g for g in decomp_gates if g.status != GateStatus.PENDING.value]

        if not decomp_gates:
            print("Running Build Decomposition phase...")
            gate = await session.run_build_decomposition()
            _print_gate_detail(gate)
            return 0
        elif resolved:
            print("Processing decomposition response, storing task queue...")
            tasks = await session.process_decomposition_response(resolved[-1])
            print(f"\n{len(tasks)} tasks queued for build supervision.")
            for t in tasks:
                dep_str = f" (deps: {', '.join(t.depends_on)})" if t.depends_on else ""
                print(f"  [Group {t.parallel_group}] {t.task_name} ({t.task_type}){dep_str}")
            return 0

    elif phase == "build_supervision":
        # Check for TIER_COMPLETE gate
        tier_gates = [g for g in project.gates if g.gate_type == GateType.TIER_COMPLETE.value]
        resolved = [g for g in tier_gates if g.status != GateStatus.PENDING.value]

        if not tier_gates:
            print(f"Phase: {phase} — tasks decomposed and queued.")
            print(f"  Task queue: {len(project.task_queue)} tasks")
            print(f"\nRun 'nexus-orch build --project {project.project_id}' to dispatch builders.")
            return 0
        elif resolved:
            # Advance to validation phase
            project.current_phase = "validation"
            project.save(session.projects_dir)
            print(f"Build tier complete. Advancing to validation phase.")
            print(f"  Completed tasks: {len(project.completed_tasks)}")
            print(f"\nRun 'nexus-orch review --project {project.project_id}' to start review pipeline.")
            return 0

    elif phase == "validation":
        # Check for review gate
        from orchestration.models import ReviewVerdict
        review_gates = [
            g for g in project.gates
            if g.gate_type in (GateType.TIER_COMPLETE.value, GateType.SCOPE_CHANGE.value)
            and g.phase == "validation"
        ]
        resolved = [g for g in review_gates if g.status != GateStatus.PENDING.value]

        if not review_gates:
            print(f"Phase: {phase} — ready for review.")
            print(f"\nRun 'nexus-orch review --project {project.project_id}' to start review pipeline.")
            return 0
        elif resolved:
            print(f"Phase: {phase} — review complete.")
            results = await session.process_review_response(resolved[-1])
            accepted = sum(1 for r in results if r.verdict == ReviewVerdict.ACCEPT.value)
            print(f"  {accepted}/{len(results)} tasks accepted. Artifacts registered.")
            return 0

    print(f"Phase: {phase} — no architect action available.")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Respond to a pending gate with approval."""
    from orchestration.gate_manager import GateManager

    projects_dir = Path(args.projects_dir)

    try:
        project = ProjectState.load(args.project, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{args.project}' not found", file=sys.stderr)
        return 1

    gate_manager = GateManager(projects_dir)

    # Determine response type from args
    response = _build_approve_response(args)
    if response is None:
        return 1

    try:
        gate = gate_manager.respond_to_gate(project, args.gate, response)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    project.save(projects_dir)

    print(f"Gate {gate.gate_id} — {gate.status}")
    if gate.conditions:
        print(f"  Conditions: {'; '.join(gate.conditions)}")
    print(f"\nRun 'nexus-orch architect --project {args.project}' to continue.")
    return 0


def _build_approve_response(args: argparse.Namespace) -> GateResponse | None:
    """Build a GateResponse from CLI args."""
    if getattr(args, "combine", None):
        return GateResponse(
            response_type=GateResponseType.COMBINE.value,
            combine_instructions=args.combine,
        )
    elif getattr(args, "revise", None):
        return GateResponse(
            response_type=GateResponseType.REVISE_AND_PROCEED.value,
            revision_feedback=args.revise,
        )
    elif getattr(args, "redirect", None):
        return GateResponse(
            response_type=GateResponseType.EXPLORE_DIFFERENTLY.value,
            redirect_instructions=args.redirect,
        )
    elif getattr(args, "choice", None) and getattr(args, "modify", None):
        return GateResponse(
            response_type=GateResponseType.CHOOSE_WITH_MODIFICATIONS.value,
            chosen_option=args.choice,
            modifications=args.modify,
        )
    elif getattr(args, "choice", None):
        return GateResponse(
            response_type=GateResponseType.CHOOSE.value,
            chosen_option=args.choice,
        )
    else:
        print(
            "Error: Must specify --choice, --combine, --revise, or --redirect",
            file=sys.stderr,
        )
        return None


def cmd_reject(args: argparse.Namespace) -> int:
    """Reject a pending gate."""
    from orchestration.gate_manager import GateManager

    projects_dir = Path(args.projects_dir)

    try:
        project = ProjectState.load(args.project, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{args.project}' not found", file=sys.stderr)
        return 1

    gate_manager = GateManager(projects_dir)
    response = GateResponse(
        response_type=GateResponseType.REJECT.value,
        rejection_reason=args.feedback,
    )

    try:
        gate = gate_manager.respond_to_gate(project, args.gate, response)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    project.save(projects_dir)

    print(f"Gate {gate.gate_id} — REJECTED")
    print(f"  Reason: {args.feedback}")
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    """List all gates for a project."""
    from orchestration.gate_manager import GateManager

    projects_dir = Path(args.projects_dir)

    if not args.project:
        print("Error: --project is required", file=sys.stderr)
        return 1

    gate_manager = GateManager(projects_dir)
    gates = gate_manager.list_gates(args.project)

    if not gates:
        print("No gates found.")
        return 0

    print(f"Gates for project {args.project}:")
    for g in gates:
        status_marker = {
            "pending": "[PENDING]",
            "approved": "[APPROVED]",
            "rejected": "[REJECTED]",
            "deferred": "[DEFERRED]",
        }.get(g.status, f"[{g.status}]")

        rec = f"  (recommended: {g.recommended_option})" if g.recommended_option else ""
        print(f"  {g.gate_id}  {status_marker}  {g.gate_type}  {g.summary}{rec}")

    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Run the review pipeline on completed builder output."""
    from orchestration.architect import ArchitectSession, default_connector_factory
    from orchestration.constitution import ConstitutionEnforcer
    from orchestration.gate_manager import GateManager
    from orchestration.models import ReviewVerdict

    projects_dir = Path(args.projects_dir)
    docs_dir = Path(args.docs_dir)

    try:
        project = ProjectState.load(args.project, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{args.project}' not found", file=sys.stderr)
        return 1

    # Allow review from build_supervision (with resolved TIER_COMPLETE) or validation
    if project.current_phase not in ("build_supervision", "validation"):
        print(
            f"Error: Project is in phase '{project.current_phase}'. "
            f"Review requires 'build_supervision' (with completed build) or 'validation' phase.",
            file=sys.stderr,
        )
        return 1

    if not project.completed_tasks:
        print("Error: No completed tasks to review.", file=sys.stderr)
        return 1

    if project.pending_gate:
        _print_gate_detail(project.pending_gate)
        print("\nUse 'approve' or 'reject' to respond before continuing.")
        return 0

    constitution = ConstitutionEnforcer(docs_dir)
    gate_manager = GateManager(projects_dir)
    role_config = _load_role_config("architect", str(docs_dir))

    session = ArchitectSession(
        project=project,
        projects_dir=projects_dir,
        constitution=constitution,
        gate_manager=gate_manager,
        role_config=role_config,
    )

    print(f"Running review pipeline on {len(project.completed_tasks)} completed tasks...")

    gate = asyncio.run(session.run_review_phase())

    review_results = getattr(session, "_review_results", [])
    if review_results:
        print(f"\nReview Results:")
        for r in review_results:
            print(f"  {r.task_id}: {r.verdict.upper()}")

    _print_gate_detail(gate)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Dispatch builders for all queued tasks."""
    from orchestration.architect import ArchitectSession, default_connector_factory
    from orchestration.constitution import ConstitutionEnforcer
    from orchestration.gate_manager import GateManager

    projects_dir = Path(args.projects_dir)
    docs_dir = Path(args.docs_dir)

    try:
        project = ProjectState.load(args.project, projects_dir)
    except FileNotFoundError:
        print(f"Error: Project '{args.project}' not found", file=sys.stderr)
        return 1

    if project.current_phase != "build_supervision":
        print(
            f"Error: Project is in phase '{project.current_phase}', "
            f"not 'build_supervision'. Run architect phases first.",
            file=sys.stderr,
        )
        return 1

    if project.pending_gate:
        _print_gate_detail(project.pending_gate)
        print("\nUse 'approve' or 'reject' to respond before continuing.")
        return 0

    if not project.task_queue:
        print("No tasks in queue to dispatch.")
        return 0

    constitution = ConstitutionEnforcer(docs_dir)
    gate_manager = GateManager(projects_dir)
    role_config = _load_role_config("architect", str(docs_dir))

    session = ArchitectSession(
        project=project,
        projects_dir=projects_dir,
        constitution=constitution,
        gate_manager=gate_manager,
        role_config=role_config,
    )

    print(f"Dispatching {len(project.task_queue)} builder tasks...")

    gate = asyncio.run(session.run_build_supervision())

    build_result = getattr(session, "_build_result", None)
    if build_result:
        print(f"\nBuild Results:")
        print(f"  Completed: {build_result.completed_count}")
        print(f"  Failed:    {build_result.failed_count}")
        if build_result.total_input_tokens or build_result.total_output_tokens:
            print(
                f"  Tokens:    {build_result.total_input_tokens} in / "
                f"{build_result.total_output_tokens} out"
            )
        if build_result.questions_for_architect:
            print(f"  Builder questions: {len(build_result.questions_for_architect)}")

    _print_gate_detail(gate)
    return 0


def _print_gate_detail(gate) -> None:
    """Print detailed gate information to stdout."""
    print(f"\n{'=' * 60}")
    print(f"GATE: {gate.gate_id}")
    print(f"Type:   {gate.gate_type}")
    print(f"Status: {gate.status}")
    print(f"{'=' * 60}")
    print(f"\n{gate.summary}\n")

    if gate.architect_raw_response:
        print("--- Architect's Response ---")
        print(gate.architect_raw_response)
        print("----------------------------\n")

    if gate.questions:
        print("Questions:")
        for i, q in enumerate(gate.questions, 1):
            print(f"  {i}. {q}")
        print()

    if gate.options:
        print("Options:")
        for opt in gate.options:
            letter = opt.get("letter", "?")
            name = opt.get("name", "")
            rec = " [RECOMMENDED]" if opt.get("is_recommended") else ""
            print(f"  {letter}: {name}{rec}")
        print()

    if gate.recommended_option:
        print(f"Recommended: Option {gate.recommended_option}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus-orch",
        description="Nexus Orchestrator — Constitutional multi-agent engineering CLI",
    )
    parser.add_argument(
        "--projects-dir",
        default=DEFAULT_PROJECTS_DIR,
        help=f"Path to projects directory (default: {DEFAULT_PROJECTS_DIR})",
    )
    parser.add_argument(
        "--docs-dir",
        default=DEFAULT_DOCS_DIR,
        help=f"Path to constitutional docs directory (default: {DEFAULT_DOCS_DIR})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- new ---
    new_parser = subparsers.add_parser("new", help="Create a new project from a Vision Contract")
    new_parser.add_argument(
        "--vision", required=True,
        help="Path to Vision Contract markdown file",
    )
    new_parser.add_argument(
        "--relaxed", action="store_true", default=False,
        help="Accept freeform input without validating required fields",
    )

    # --- status ---
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument(
        "--project", default="",
        help="Project ID (omit to list all projects)",
    )

    # --- architect ---
    arch_parser = subparsers.add_parser("architect", help="Start or continue Architect session")
    arch_parser.add_argument("--project", required=True, help="Project ID")

    # --- approve ---
    approve_parser = subparsers.add_parser("approve", help="Respond to a pending gate")
    approve_parser.add_argument("--project", required=True, help="Project ID")
    approve_parser.add_argument("--gate", required=True, help="Gate ID")
    approve_parser.add_argument("--choice", default="", help="Option letter (A, B, C, D)")
    approve_parser.add_argument("--modify", default="", help="Modifications to apply with choice")
    approve_parser.add_argument("--combine", default="", help="Instructions for combining options")
    approve_parser.add_argument("--revise", default="", help="Feedback for revise-and-proceed")
    approve_parser.add_argument("--redirect", default="", help="Instructions for exploring differently")

    # --- reject ---
    reject_parser = subparsers.add_parser("reject", help="Reject a pending gate")
    reject_parser.add_argument("--project", required=True, help="Project ID")
    reject_parser.add_argument("--gate", required=True, help="Gate ID")
    reject_parser.add_argument("--feedback", required=True, help="Rejection reason")

    # --- gates ---
    gates_parser = subparsers.add_parser("gates", help="List gates for a project")
    gates_parser.add_argument("--project", required=True, help="Project ID")

    # --- build ---
    build_parser = subparsers.add_parser("build", help="Dispatch builders for queued tasks")
    build_parser.add_argument("--project", required=True, help="Project ID")

    # --- review ---
    review_parser = subparsers.add_parser("review", help="Run review pipeline on builder output")
    review_parser.add_argument("--project", required=True, help="Project ID")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "new": cmd_new,
        "status": cmd_status,
        "architect": cmd_architect,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "gates": cmd_gates,
        "build": cmd_build,
        "review": cmd_review,
    }

    handler = commands.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
