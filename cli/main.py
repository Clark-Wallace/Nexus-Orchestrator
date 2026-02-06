"""CLI entry point for Nexus Orchestrator.

Tier 1 commands:
  nexus-orch new --vision <path>       Create a new project from a Vision Contract
  nexus-orch status --project <id>     Show project status

Future tiers add: approve, reject, lineage, decisions, costs, run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestration.models import VisionContract, VisionValidationError
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
    }

    handler = commands.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
