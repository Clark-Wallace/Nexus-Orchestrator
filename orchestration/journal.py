"""Architect's Journal — append-only reasoning log.

Doc 07 §Architect's Journal: Captures not just decisions but the reasoning context
behind them. Persists across sessions. Loaded into Architect context on resume.

Storage: projects/{project_id}/architect_journal.md — append-only.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


JOURNAL_SEPARATOR = "\n" + "=" * 60 + "\n"

ENTRY_TEMPLATE = """\
JOURNAL ENTRY
=============
Date:       {date}
Phase:      {phase}
Tier:       {tier}

Context:
  {context}

Key reasoning:
  {reasoning}

Options explored:
  {options_explored}

Open questions:
  {open_questions}

Concerns:
  {concerns}

Notes for next session:
  {notes}
"""


def format_entry(
    phase: str,
    tier: int,
    context: str,
    reasoning: str,
    options_explored: str = "None beyond presented options.",
    open_questions: str = "None at this time.",
    concerns: str = "None at this time.",
    notes: str = "",
) -> str:
    """Format a journal entry per Doc 07 §Architect's Journal format."""
    return ENTRY_TEMPLATE.format(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        phase=phase,
        tier=tier,
        context=context,
        reasoning=reasoning,
        options_explored=options_explored,
        open_questions=open_questions,
        concerns=concerns,
        notes=notes,
    )


def append_entry(journal_path: str | Path, entry: str) -> None:
    """Append a journal entry to the journal file."""
    journal_path = Path(journal_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if journal_path.exists():
        existing = journal_path.read_text(encoding="utf-8")

    separator = JOURNAL_SEPARATOR if existing.strip() else ""
    journal_path.write_text(
        existing + separator + entry + "\n",
        encoding="utf-8",
    )


def load_entries(journal_path: str | Path) -> list[str]:
    """Load all journal entries from the journal file.

    Returns a list of entry strings, split on the separator.
    """
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return []

    text = journal_path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # Split on the inter-entry separator (60 '=' signs), not the entry header (13 '=' signs)
    entries = re.split(r"\n={50,}\n", text)
    return [e.strip() for e in entries if e.strip()]


def load_recent_entries(journal_path: str | Path, count: int = 3) -> list[str]:
    """Load the last N journal entries. Used by ConstitutionEnforcer for context."""
    entries = load_entries(journal_path)
    return entries[-count:]


def journal_path_for_project(project_id: str, projects_dir: str | Path) -> Path:
    """Return the journal file path for a project."""
    return Path(projects_dir) / project_id / "architect_journal.md"
