"""Constitution Enforcer — loads constitutional docs, builds scoped agent contexts.

Doc 08 §2: Loads the constitutional document stack and validates all agent outputs.
Implements the Context Budget table from Doc 07.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from orchestration.models import (
    BuilderTaskContract,
    Phase,
    TaskType,
)

if TYPE_CHECKING:
    from orchestration.project_state import ProjectState


# ---------------------------------------------------------------------------
# Document Index — maps doc number to canonical filename pattern
# ---------------------------------------------------------------------------

DOC_INDEX = {
    0: "00_",
    1: "01_",
    2: "02_",
    3: "03_",
    4: "04_",
    5: "05_",
    6: "06_",
    7: "07_",
    8: "08_",
    9: "09_",
}

# ---------------------------------------------------------------------------
# Context Budget — Doc 07 §Context Budget
# ---------------------------------------------------------------------------

# Architect: additional docs loaded per phase
ARCHITECT_PHASE_CONTEXT: dict[str, list[tuple[int, str | None]]] = {
    # Phase -> list of (doc_number, section_filter_or_None_for_full)
    Phase.VISION_INTAKE.value: [
        (1, "principles_summary"),  # Doc 01 summary (principles list only)
    ],
    Phase.SYSTEM_DESIGN.value: [
        (1, None),  # Doc 01 full
        (5, "decision_generation_pipeline"),  # Doc 05 §Decision Generation Pipeline
    ],
    Phase.DETAILED_DESIGN.value: [
        (3, None),  # Doc 03 full (Action Catalog)
        (4, None),  # Doc 04 full (Contract Spec)
        (5, None),  # Doc 05 full
    ],
    Phase.BUILD_DECOMPOSITION.value: [
        (3, "category_index"),  # Doc 03 category index (not full verb details)
    ],
    Phase.BUILD_SUPERVISION.value: [
        (3, "relevant_categories"),  # Doc 03 (relevant categories only)
        (4, "validation_pipeline"),  # Doc 04 §Validation Pipeline
    ],
    Phase.VALIDATION.value: [
        (5, None),  # Doc 05 full
        (4, "determinism_guarantee"),  # Doc 04 §Determinism Guarantee
    ],
}

# Builder: additional docs loaded per task type
BUILDER_TASK_CONTEXT: dict[str, list[tuple[int, str | None]]] = {
    TaskType.STATE_SCHEMA.value: [
        (2, "state_model"),  # Doc 02 §2 (State Model)
    ],
    TaskType.FLOW.value: [
        (2, "flows"),  # Doc 02 §5 (Flows)
        (3, "categories_a_c_d"),  # Doc 03 categories A, C, D
    ],
    TaskType.CONSTRAINT.value: [
        (2, "constraints"),  # Doc 02 §6 (Constraints)
        (4, "constraint_supremacy"),  # Doc 04 §Constraint Supremacy
    ],
    TaskType.FAILURE_RECOVERY.value: [
        (2, "failure_recovery"),  # Doc 02 §8
        (3, "categories_e_f_l"),  # Doc 03 categories E, F, L
    ],
    TaskType.DEPENDENCY_CASCADE.value: [
        (2, "dependencies"),  # Doc 02 §7
        (3, "categories_c_g"),  # Doc 03 categories C, G
    ],
    TaskType.UX_LAYER.value: [
        (5, None),  # Doc 05 full
        (4, "ux_display"),  # Doc 04 §UX Display Requirements
    ],
    TaskType.GENERAL.value: [],
}


class ConstitutionEnforcer:
    """Loads constitutional documents and builds scoped context for agents.

    Responsibilities (Tier 1 — doc loading and context building):
    - Load all constitutional docs from the doc stack directory
    - Build Architect context per phase (Context Budget table)
    - Build Builder context per task type (Context Budget table)

    Validation methods (Tiers 4+) are stubbed for future implementation.
    """

    def __init__(self, doc_stack_path: str | Path):
        """Load all constitutional documents from the given directory."""
        self.doc_stack_path = Path(doc_stack_path)
        self.docs: dict[int, str] = {}
        self.doc_paths: dict[int, Path] = {}
        self._load_docs()

    def _load_docs(self) -> None:
        """Scan the doc stack directory and load all numbered markdown files."""
        if not self.doc_stack_path.exists():
            raise FileNotFoundError(
                f"Constitutional doc stack not found at {self.doc_stack_path}"
            )

        for path in sorted(self.doc_stack_path.iterdir()):
            if not path.suffix == ".md":
                continue
            # Match numbered docs: 00_, 01_, ..., 09_
            match = re.match(r"^(\d{2})_", path.name)
            if match:
                doc_num = int(match.group(1))
                self.docs[doc_num] = path.read_text(encoding="utf-8")
                self.doc_paths[doc_num] = path

    @property
    def loaded_doc_numbers(self) -> list[int]:
        return sorted(self.docs.keys())

    def get_doc(self, doc_num: int) -> str:
        """Return the full text of a constitutional document by number."""
        if doc_num not in self.docs:
            raise KeyError(f"Doc {doc_num:02d} not found in loaded docs: {self.loaded_doc_numbers}")
        return self.docs[doc_num]

    def get_doc_section(self, doc_num: int, section_key: str) -> str:
        """Extract a section from a document.

        Section keys are semantic identifiers that map to heading-based extraction.
        If the section can't be found, returns the full document to avoid data loss.
        """
        full_text = self.get_doc(doc_num)
        extracted = _extract_section(full_text, section_key)
        return extracted if extracted else full_text

    # ------------------------------------------------------------------
    # Architect Context — Doc 07 §Context Budget, Architect section
    # ------------------------------------------------------------------

    def build_architect_context(
        self,
        project: "ProjectState",
        journal_entries: list[str] | None = None,
    ) -> str:
        """Construct the Architect's session context string.

        Always loaded:
        - Doc 07 (AI Architect Constitution) — full
        - Doc 06 (Vision Contract) — project's filled version
        - Doc 02 (Architecture Template) — project's current version
        - Architect's Journal — last 3 entries
        - Project status block

        Additional docs by phase — per Context Budget table.
        """
        parts: list[str] = []

        # --- Always loaded ---
        parts.append("=" * 60)
        parts.append("CONSTITUTIONAL CONTEXT — ARCHITECT ROLE")
        parts.append("=" * 60)

        # Doc 07 — full
        parts.append("\n--- Doc 07: AI Architect Constitution ---\n")
        parts.append(self.get_doc(7))

        # Vision Contract — project's version
        parts.append("\n--- Vision Contract (This Project) ---\n")
        if project.vision_contract.raw_markdown:
            parts.append(project.vision_contract.raw_markdown)
        else:
            parts.append(project.vision_contract.to_json())

        # Architecture Template — project's current version (or template if not filled)
        parts.append("\n--- Architecture Template (Current) ---\n")
        if project.architecture_template:
            parts.append(project.architecture_template)
        elif 2 in self.docs:
            parts.append(self.get_doc(2))

        # Architect's Journal — last 3 entries
        if journal_entries:
            parts.append("\n--- Architect's Journal (Recent) ---\n")
            for entry in journal_entries[-3:]:
                parts.append(entry)
                parts.append("")

        # Project status block
        parts.append("\n--- Project Status ---\n")
        parts.append(project.status_summary())

        # --- Phase-specific context ---
        phase = project.current_phase
        phase_docs = ARCHITECT_PHASE_CONTEXT.get(phase, [])

        if phase_docs:
            parts.append("\n--- Phase-Specific Context ---\n")
            for doc_num, section_key in phase_docs:
                if doc_num not in self.docs:
                    continue
                if section_key is None:
                    parts.append(f"\n--- Doc {doc_num:02d} (Full) ---\n")
                    parts.append(self.get_doc(doc_num))
                else:
                    parts.append(f"\n--- Doc {doc_num:02d} §{section_key} ---\n")
                    parts.append(self.get_doc_section(doc_num, section_key))

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Builder Context — Doc 07 §Context Budget, Builder section
    # ------------------------------------------------------------------

    def build_builder_context(
        self,
        task: BuilderTaskContract,
    ) -> str:
        """Construct a Builder's session context string.

        Always loaded:
        - Doc 00 (Session Preamble)
        - Builder Task Contract for this task

        Additional docs by task type — per Context Budget table.

        Builder cannot see full architecture or other tasks.
        """
        parts: list[str] = []

        parts.append("=" * 60)
        parts.append("CONSTITUTIONAL CONTEXT — BUILDER ROLE")
        parts.append("=" * 60)

        # Doc 00 — Session Preamble (always)
        parts.append("\n--- Doc 00: Session Preamble ---\n")
        if 0 in self.docs:
            parts.append(self.get_doc(0))

        # Builder Task Contract
        parts.append("\n--- Builder Task Contract ---\n")
        parts.append(_format_task_contract(task))

        # Task-type-specific context
        task_type = task.task_type
        task_docs = BUILDER_TASK_CONTEXT.get(task_type, [])

        if task_docs:
            parts.append("\n--- Task-Specific Context ---\n")
            for doc_num, section_key in task_docs:
                if doc_num not in self.docs:
                    continue
                if section_key is None:
                    parts.append(f"\n--- Doc {doc_num:02d} (Full) ---\n")
                    parts.append(self.get_doc(doc_num))
                else:
                    parts.append(f"\n--- Doc {doc_num:02d} §{section_key} ---\n")
                    parts.append(self.get_doc_section(doc_num, section_key))

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Validation stubs (Tier 4+)
    # ------------------------------------------------------------------

    def validate_architect_output(self, output: str, project: "ProjectState") -> dict:
        """Stub — constitutional validation of architect output. Tier 4+."""
        return {"valid": True, "violations": []}

    def validate_builder_output(self, output: str, task: BuilderTaskContract) -> dict:
        """Stub — constitutional validation of builder output. Tier 4+."""
        return {"valid": True, "violations": []}


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

# Map section keys to heading patterns for extraction
_SECTION_PATTERNS: dict[str, list[str]] = {
    # Doc 01
    "principles_summary": [r"^#+\s"],  # All headings = principle names
    # Doc 02
    "state_model": [r"(?i)state\s+model"],
    "flows": [r"(?i)\bflows?\b"],
    "constraints": [r"(?i)constraint"],
    "dependencies": [r"(?i)dependenc"],
    "failure_recovery": [r"(?i)failure", r"(?i)recovery"],
    # Doc 03
    "category_index": [r"(?i)^#+\s.*categor", r"(?i)^#+\s.*[A-M]\."],
    "categories_a_c_d": [r"(?i)resource\s+control", r"(?i)routing.*flow", r"(?i)load.*demand"],
    "categories_e_f_l": [r"(?i)asset.*infrastructure", r"(?i)maintenance.*repair", r"(?i)risk.*safety"],
    "categories_c_g": [r"(?i)routing.*flow", r"(?i)priority.*policy"],
    "relevant_categories": [r"(?i)^#+\s.*[A-M]\."],
    # Doc 04
    "validation_pipeline": [r"(?i)validation\s+pipeline"],
    "constraint_supremacy": [r"(?i)constraint\s+supremacy"],
    "determinism_guarantee": [r"(?i)determinism"],
    "ux_display": [r"(?i)ux\s+display", r"(?i)user\s+selection"],
    # Doc 05
    "decision_generation_pipeline": [r"(?i)decision.*pipeline", r"(?i)decision.*generation"],
}


def _extract_section(full_text: str, section_key: str) -> str:
    """Extract sections of a markdown document matching the given key.

    Uses heading-based extraction: finds headings matching the patterns,
    then captures everything from that heading to the next heading of equal
    or higher level.
    """
    patterns = _SECTION_PATTERNS.get(section_key)
    if not patterns:
        return ""

    # Special case: principles_summary — extract just the heading lines
    if section_key == "principles_summary":
        headings = []
        for line in full_text.splitlines():
            if re.match(r"^#+\s", line):
                headings.append(line)
        return "\n".join(headings) if headings else ""

    # Special case: category_index — extract just category headings and first line
    if section_key == "category_index":
        return _extract_category_index(full_text)

    # General section extraction
    lines = full_text.splitlines()
    sections: list[str] = []
    capturing = False
    capture_level = 0
    current: list[str] = []

    for line in lines:
        heading_match = re.match(r"^(#+)\s+(.*)$", line)

        if heading_match:
            level = len(heading_match.group(1))

            # Check if this heading ends a capture
            if capturing and level <= capture_level:
                sections.append("\n".join(current))
                current = []
                capturing = False

            # Check if this heading starts a capture
            heading_text = line
            for pattern in patterns:
                if re.search(pattern, heading_text):
                    capturing = True
                    capture_level = level
                    current = [line]
                    break
        elif capturing:
            current.append(line)

    # Flush final capture
    if current:
        sections.append("\n".join(current))

    return "\n\n".join(sections)


def _extract_category_index(text: str) -> str:
    """Extract category headings from Doc 03 (Action Primitive Catalog).

    Returns just the category names and verb counts, not full verb details.
    """
    lines = text.splitlines()
    result: list[str] = []
    in_category = False
    verb_count = 0

    for line in lines:
        # Match category headings like "## A. Resource Control" or "### A. Resource Control"
        if re.match(r"^#{2,3}\s+[A-M]\.\s+", line):
            if in_category and verb_count > 0:
                result.append(f"  ({verb_count} verbs)")
            result.append(line)
            in_category = True
            verb_count = 0
        elif in_category:
            # Count verb entries (typically bold items or numbered items)
            if re.match(r"^\*\*\w+", line) or re.match(r"^\d+\.\s+\*\*", line):
                verb_count += 1
            # Also count items like "- `verb_name`"
            if re.match(r"^[-*]\s+`\w+", line):
                verb_count += 1

    if in_category and verb_count > 0:
        result.append(f"  ({verb_count} verbs)")

    return "\n".join(result)


def _format_task_contract(task: BuilderTaskContract) -> str:
    """Format a BuilderTaskContract as the markdown block per Doc 07."""
    lines = [
        "BUILDER TASK CONTRACT",
        "=====================",
        f"Task ID:            {task.task_id}",
        f"Task Name:          {task.task_name}",
        f"Build Tier:         {task.build_tier}",
        f"Subsystem:          {task.subsystem}",
        "",
        "Objective:",
        f"  {task.objective}",
        "",
        "Inputs:",
    ]
    for inp in task.inputs:
        lines.append(f"  - {inp}")

    lines.extend(["", "Scope — MUST Build:"])
    for item in task.scope_must_build:
        lines.append(f"  - {item}")

    lines.extend(["", "Scope — MUST NOT Touch:"])
    for item in task.scope_must_not_touch:
        lines.append(f"  - {item}")

    lines.extend(["", "Schema to Implement:", f"  {task.schema_to_implement}", ""])

    lines.append("Rules to Implement:")
    for rule in task.rules_to_implement:
        lines.append(f"  - {rule}")

    lines.extend(["", "Constraints to Enforce:"])
    for c in task.constraints_to_enforce:
        lines.append(f"  - {c}")

    lines.extend(["", "Verbs Used:"])
    for v in task.verbs_used:
        lines.append(f"  - {v}")

    lines.extend([
        "",
        "Interfaces:",
        "  Receives:",
    ])
    for r in task.interfaces_receives:
        lines.append(f"    - {r}")
    lines.append("  Produces:")
    for p in task.interfaces_produces:
        lines.append(f"    - {p}")

    lines.extend(["", "Test Criteria:"])
    for tc in task.test_criteria:
        lines.append(f"  - [ ] {tc}")

    lines.extend([
        "",
        "Output Manifest Required:",
        "  Produce a builder_output.json manifest per the Builder Output Manifest spec.",
    ])

    return "\n".join(lines)
