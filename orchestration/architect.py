"""Architect Session — manages the AI Architect's design conversation.

Creates and manages NexusConnector sessions for the Architect role.
All AI interaction goes through Nexus sessions — no direct API calls.

Tier 2 implements:
- Session creation with constitutional context as system prompt
- Phase 1: Vision intake (identify gaps, produce clarifying questions)
- Phase 2-3: Architecture generation (produce gate cards with options)
- Conversation persistence across CLI invocations
- Gate integration (pause at gates, resume after human response)
- Journal integration (append entries after each phase)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestration.constitution import ConstitutionEnforcer
from orchestration.gate_manager import GateManager
from orchestration.journal import (
    append_entry,
    format_entry,
    journal_path_for_project,
    load_recent_entries,
)
from orchestration.models import (
    Gate,
    GateOption,
    GateResponse,
    GateType,
    Phase,
)
from orchestration.project_state import ProjectState


# ---------------------------------------------------------------------------
# Connector protocol — allows mocking for tests
# ---------------------------------------------------------------------------

class ConnectorProtocol(Protocol):
    """Minimal interface we need from NexusConnector."""
    conversation_history: list
    session_id: str

    async def send_message(self, message: str, **kwargs: Any) -> dict[str, Any]: ...


ConnectorFactory = Callable[..., ConnectorProtocol]


def default_connector_factory(
    provider: str,
    model: str,
    system_prompt: str,
    **kwargs: Any,
) -> ConnectorProtocol:
    """Create a real NexusConnector instance."""
    from nexus import NexusConnector
    return NexusConnector(
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        max_iterations=1,
        auto_execute=False,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def _session_path(project_id: str, projects_dir: str | Path) -> Path:
    return Path(projects_dir) / project_id / "architect_session.json"


def save_session_messages(
    project_id: str,
    projects_dir: str | Path,
    messages: list[dict],
    session_id: str = "",
) -> None:
    """Persist the Architect session's conversation history."""
    path = _session_path(project_id, projects_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "session_id": session_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_session_messages(
    project_id: str,
    projects_dir: str | Path,
) -> tuple[str, list[dict]]:
    """Load persisted session messages. Returns (session_id, messages)."""
    path = _session_path(project_id, projects_dir)
    if not path.exists():
        return "", []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("session_id", ""), data.get("messages", [])


def _serialize_history(connector: ConnectorProtocol) -> list[dict]:
    """Extract serializable message dicts from connector history."""
    messages = []
    for msg in connector.conversation_history:
        if hasattr(msg, "role"):
            messages.append({
                "role": msg.role,
                "content": msg.content if hasattr(msg, "content") else str(msg),
            })
        elif isinstance(msg, dict):
            messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# Architect Session
# ---------------------------------------------------------------------------

class ArchitectSession:
    """Manages the Architect AI session across phases.

    All AI interaction goes through a NexusConnector session.
    Constitutional context is injected as the system prompt.
    """

    def __init__(
        self,
        project: ProjectState,
        projects_dir: str | Path,
        constitution: ConstitutionEnforcer,
        gate_manager: GateManager,
        connector_factory: ConnectorFactory = default_connector_factory,
        role_config: dict | None = None,
    ):
        self.project = project
        self.projects_dir = Path(projects_dir)
        self.constitution = constitution
        self.gate_manager = gate_manager
        self.connector_factory = connector_factory
        self.role_config = role_config or {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
        }
        self.connector: ConnectorProtocol | None = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self) -> ConnectorProtocol:
        """Create a new Architect session with constitutional context.

        The system prompt includes:
        - Doc 07 (AI Architect Constitution) — full
        - Vision Contract — project's version
        - Architecture Template — current version
        - Architect's Journal — last 3 entries
        - Project status block
        - Phase-specific docs per Context Budget table
        """
        journal_entries = load_recent_entries(
            journal_path_for_project(self.project.project_id, self.projects_dir)
        )

        system_prompt = self.constitution.build_architect_context(
            self.project,
            journal_entries=journal_entries,
        )

        self.connector = self.connector_factory(
            provider=self.role_config.get("provider", "anthropic"),
            model=self.role_config.get("model", "claude-sonnet-4-5-20250929"),
            system_prompt=system_prompt,
        )

        self.project.architect_session_id = getattr(
            self.connector, "session_id", "session_unknown"
        )
        return self.connector

    def resume_session(self) -> ConnectorProtocol:
        """Resume a persisted Architect session.

        Recreates the connector with current constitutional context
        and replays the conversation history.
        """
        session_id, messages = load_session_messages(
            self.project.project_id, self.projects_dir
        )

        connector = self.create_session()

        # Replay conversation history
        for msg in messages:
            _inject_message(connector, msg)

        return connector

    def save_session(self) -> None:
        """Persist the current session's conversation history."""
        if not self.connector:
            return
        messages = _serialize_history(self.connector)
        save_session_messages(
            self.project.project_id,
            self.projects_dir,
            messages,
            session_id=getattr(self.connector, "session_id", ""),
        )

    # ------------------------------------------------------------------
    # Phase 1 — Vision Intake (Doc 07 §Phase 1)
    # ------------------------------------------------------------------

    async def run_vision_intake(self) -> Gate:
        """Send the Vision Contract to the Architect and get clarifying questions.

        Process:
        1. Send vision contract to Architect
        2. Architect identifies gaps and produces questions
        3. Create a vision_confirmed gate
        4. Save session and return gate

        Returns the pending gate for human response.
        """
        if not self.connector:
            self.create_session()

        self.project.current_phase = Phase.VISION_INTAKE.value

        vision_md = self.project.vision_contract.raw_markdown
        if not vision_md:
            vision_md = self.project.vision_contract.to_json()

        prompt = (
            "Here is the Vision Contract for this project:\n\n"
            f"{vision_md}\n\n"
            "Review this vision completely. Following Doc 07 Phase 1 (Vision Intake):\n"
            "1. Identify any gaps — what's missing that you need to design?\n"
            "2. List your clarifying questions (batch them, don't drip-feed)\n"
            "3. Present your understanding of the vision back to the human\n"
            "4. If the vision has ambiguity, present 2-3 interpretive framings\n\n"
            "Format your response clearly with sections for:\n"
            "- Your understanding of the vision\n"
            "- Clarifying questions (if any)\n"
            "- Any interpretive framings (if the vision is ambiguous)"
        )

        response = await self.connector.send_message(prompt)
        content = response.get("content", "")

        # Extract questions from the response
        questions = _extract_questions(content)

        # Create the vision_confirmed gate
        gate = self.gate_manager.create_gate(
            project=self.project,
            gate_type=GateType.VISION_CONFIRMED,
            summary="Architect has reviewed the Vision Contract and has questions/observations.",
            architect_raw_response=content,
            questions=questions,
        )

        # Append journal entry
        _append_phase_journal(
            self.project, self.projects_dir,
            context="Reviewed the Vision Contract and identified gaps/questions.",
            reasoning="Need human clarification before proceeding to system design.",
        )

        self.save_session()
        self.project.save(self.projects_dir)

        return gate

    async def process_vision_response(self, gate: Gate) -> None:
        """Feed the human's vision response back to the Architect.

        Called after the human responds to the vision_confirmed gate.
        Advances phase to system_design.
        """
        if not self.connector:
            self.resume_session()

        response_msg = self.gate_manager.build_response_message(gate)
        if response_msg:
            await self.connector.send_message(response_msg)

        self.project.current_phase = Phase.SYSTEM_DESIGN.value
        self.save_session()
        self.project.save(self.projects_dir)

    # ------------------------------------------------------------------
    # Phase 2-3 — System Design + Detailed Design (Doc 07 §Phase 2-3)
    # ------------------------------------------------------------------

    async def run_system_design(self) -> Gate:
        """Ask the Architect to produce system design options.

        Process:
        1. Prompt Architect for 2-4 architecture options
        2. Each option must follow the Gate Card Structure from Doc 07
        3. Architect marks a recommended option
        4. Create a system_design gate
        5. Save session and return gate

        Returns the pending gate for human choice.
        """
        if not self.connector:
            self.resume_session()

        self.project.current_phase = Phase.SYSTEM_DESIGN.value

        prompt = (
            "Now proceed to Phase 2 — System Design.\n\n"
            "Explore 2-4 viable system decompositions for this project. "
            "For each option, provide the FULL gate card format from Doc 07:\n\n"
            "OPTION [letter]: \"[Short descriptive name]\"\n\n"
            "  Summary:\n"
            "    What this option does in plain language.\n\n"
            "  Key characteristics:\n"
            "    - [2-4 defining features]\n\n"
            "  Tradeoffs:\n"
            "    Optimizes for: [what gets better]\n"
            "    Costs:         [what gets worse]\n\n"
            "  Consequence chain:\n"
            "    1st order:  [Immediate result]\n"
            "    2nd order:  [What 1st order causes]\n"
            "    3rd order:  [What 2nd order enables/prevents]\n\n"
            "  Build impact:\n"
            "    Subsystems:     [count]\n"
            "    Builder tasks:  [estimated count]\n"
            "    Estimated cost: [range]\n"
            "    Timeline:       [relative]\n\n"
            "  Risk:\n"
            "    [What could go wrong]\n\n"
            "Mark one option as RECOMMENDED with your rationale.\n"
            "Include what in the Vision Contract supports your recommendation."
        )

        response = await self.connector.send_message(prompt)
        content = response.get("content", "")

        # Parse options from response
        options = _parse_gate_options(content)
        recommended = _find_recommended(content, options)

        gate = self.gate_manager.create_gate(
            project=self.project,
            gate_type=GateType.SYSTEM_DESIGN,
            summary="Architect presents system design options. Choose a direction.",
            architect_raw_response=content,
            options=options,
            recommended_option=recommended,
        )

        _append_phase_journal(
            self.project, self.projects_dir,
            context="Produced system design options for human review.",
            reasoning=f"Presented {len(options)} options. Recommended: {recommended}.",
        )

        self.save_session()
        self.project.save(self.projects_dir)

        return gate

    async def process_design_response(self, gate: Gate) -> str:
        """Feed the human's design choice back to the Architect.

        Called after the human responds to the system_design gate.
        Architect proceeds with the chosen direction.

        Returns the Architect's confirmation/elaboration response.
        """
        if not self.connector:
            self.resume_session()

        response_msg = self.gate_manager.build_response_message(gate)

        prompt = (
            f"{response_msg}\n\n"
            "Proceed with this direction. Produce the detailed system design:\n"
            "- List all subsystems and their responsibilities\n"
            "- Define cross-system dependencies\n"
            "- Outline the primary flows\n"
            "- Note any design decisions you're making within your authority\n\n"
            "This will become the foundation of the Architecture Template."
        )

        response = await self.connector.send_message(prompt)
        content = response.get("content", "")

        # Store architecture template if produced
        if content:
            self.project.architecture_template = content

        self.project.current_phase = Phase.DETAILED_DESIGN.value

        _append_phase_journal(
            self.project, self.projects_dir,
            context="Human chose design direction. Producing detailed design.",
            reasoning="Expanding chosen option into full Architecture Template.",
        )

        self.save_session()
        self.project.save(self.projects_dir)

        return content


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _extract_questions(text: str) -> list[str]:
    """Extract questions from Architect's response text."""
    questions = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.endswith("?"):
            # Clean up bullet/number prefixes
            cleaned = stripped.lstrip("-*0123456789.) ").strip()
            if cleaned and len(cleaned) > 10:  # Skip very short fragments
                questions.append(cleaned)
    return questions


def _parse_gate_options(text: str) -> list[GateOption]:
    """Parse gate card options from Architect's response.

    Looks for the pattern:
    OPTION [letter]: "[name]"
    """
    options: list[GateOption] = []
    lines = text.splitlines()
    current_option: dict[str, Any] | None = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect option header: OPTION A: "Name" or OPTION B: "Name" ★ RECOMMENDED
        import re
        opt_match = re.match(
            r'^OPTION\s+([A-Z]):\s*["\u201c](.+?)["\u201d](.*)$', line
        )
        if opt_match:
            # Save previous option
            if current_option:
                options.append(_build_gate_option(current_option))

            letter = opt_match.group(1)
            name = opt_match.group(2)
            rest = opt_match.group(3)
            is_recommended = "RECOMMENDED" in rest.upper() if rest else False

            current_option = {
                "letter": letter,
                "name": name,
                "is_recommended": is_recommended,
                "lines": [],
            }
        elif current_option is not None:
            current_option["lines"].append(line)

        i += 1

    # Save last option
    if current_option:
        options.append(_build_gate_option(current_option))

    return options


def _build_gate_option(data: dict) -> GateOption:
    """Build a GateOption from parsed data."""
    lines = data.get("lines", [])
    text = "\n".join(lines)

    opt = GateOption(
        letter=data["letter"],
        name=data["name"],
        is_recommended=data.get("is_recommended", False),
    )

    # Parse structured fields from the text
    opt.summary = _extract_field(text, "Summary")
    opt.optimizes_for = _extract_field(text, "Optimizes for")
    opt.costs = _extract_field(text, "Costs")
    opt.consequence_1st = _extract_field(text, "1st order")
    opt.consequence_2nd = _extract_field(text, "2nd order")
    opt.consequence_3rd = _extract_field(text, "3rd order")
    opt.risk = _extract_field(text, "Risk")
    opt.estimated_cost = _extract_field(text, "Estimated cost")
    opt.timeline = _extract_field(text, "Timeline")
    opt.builder_tasks = _extract_field(text, "Builder tasks")

    # Parse subsystems count
    subsys_str = _extract_field(text, "Subsystems")
    if subsys_str:
        import re
        nums = re.findall(r"\d+", subsys_str)
        if nums:
            opt.subsystems = int(nums[0])

    # Parse key characteristics (bullet list)
    opt.key_characteristics = _extract_bullet_list(text, "Key characteristics")

    # Recommendation rationale
    if opt.is_recommended:
        opt.recommendation_rationale = _extract_field(text, "reasoning") or _extract_field(text, "rationale")

    return opt


def _extract_field(text: str, field_name: str) -> str:
    """Extract a field value from structured text like 'Field: value'."""
    import re
    pattern = rf"(?:^|\n)\s*{re.escape(field_name)}:\s*(.+?)(?:\n\s*\w|\n\n|$)"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_bullet_list(text: str, section_name: str) -> list[str]:
    """Extract a bulleted list under a section heading."""
    import re
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


def _find_recommended(text: str, options: list[GateOption]) -> str:
    """Find which option is recommended."""
    for opt in options:
        if opt.is_recommended:
            return opt.letter

    # Fallback: look for "recommended" near an option letter
    import re
    match = re.search(r"recommend(?:ed|s?).*?option\s+([A-Z])", text, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"option\s+([A-Z]).*?recommend", text, re.IGNORECASE)
    if match:
        return match.group(1)

    return ""


def _inject_message(connector: ConnectorProtocol, msg: dict) -> None:
    """Inject a message dict into the connector's conversation history."""
    try:
        from nexus.core.base_connector import Message
        connector.conversation_history.append(
            Message(role=msg["role"], content=msg.get("content", ""))
        )
    except ImportError:
        # Fallback for mock connectors
        connector.conversation_history.append(msg)


def _append_phase_journal(
    project: ProjectState,
    projects_dir: str | Path,
    context: str,
    reasoning: str,
) -> None:
    """Append a journal entry for the current phase."""
    entry = format_entry(
        phase=project.current_phase,
        tier=project.current_tier,
        context=context,
        reasoning=reasoning,
    )
    jpath = journal_path_for_project(project.project_id, projects_dir)
    append_entry(jpath, entry)
