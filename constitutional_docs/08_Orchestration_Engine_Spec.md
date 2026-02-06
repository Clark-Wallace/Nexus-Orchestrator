# Orchestration Engine Spec — Constitutional Multi-Agent Simulation Building

Extends the Nexus Connector into a multi-agent orchestration system where an AI Architect
manages AI Builders under human vision authority, governed by the constitutional document stack.

---

## Overview

The Nexus Connector provides: provider-agnostic AI communication, persistent sessions, tool execution, and stateful conversations.

This spec adds: role-based agent hierarchy, constitutional enforcement, task dispatch and review, gate-controlled workflow, and project state persistence.

```
┌─────────────────────────────────────────────────┐
│                  Human (Vision)                  │
│           Provides Vision Contract               │
│           Approves at Gates                      │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│              Orchestration Engine                 │
│                                                   │
│  ┌─────────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Project      │  │ Gate     │  │ Lineage    │  │
│  │ State Store  │  │ Manager  │  │ Tracker    │  │
│  └─────────────┘  └──────────┘  └────────────┘  │
│                                                   │
│  ┌─────────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Constitution │  │ Task     │  │ Review     │  │
│  │ Enforcer     │  │ Dispatch │  │ Engine     │  │
│  └─────────────┘  └──────────┘  └────────────┘  │
│                                                   │
└──────────┬───────────────────────┬──────────────┘
           │                       │
           ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  AI Architect    │     │  AI Builder(s)   │
│  (Nexus Session) │     │  (Nexus Sessions) │
│                  │     │                   │
│  Design authority│     │  Scoped tasks     │
│  Review authority│     │  No cross-task    │
│  Dispatch tasks  │     │  visibility       │
└─────────────────┘     └─────────────────┘
```

---

## Core Components

### 1 — Project State Store

Persistent state for the entire project lifecycle. This is the orchestration engine's
equivalent of the simulation's `world_state`.

```python
class ProjectState:
    # Identity
    project_id: str
    project_name: str
    created_at: datetime
    
    # Vision
    vision_contract: VisionContract          # Doc 06 — human input
    
    # Design (Architect output)
    architecture_template: ArchitectureTemplate  # Doc 02 — filled by Architect
    subsystem_specs: dict[str, SubsystemSpec]    # One-pagers per subsystem
    
    # Build tracking
    current_tier: int                        # 1-7, from fidelity ladder
    current_phase: Phase                     # design | build | validation
    
    # Task management
    task_queue: list[BuilderTask]            # Pending tasks
    active_tasks: dict[str, BuilderTask]     # Currently dispatched
    completed_tasks: list[CompletedTask]     # Done, with review results
    
    # Gates
    gates: list[Gate]                        # Approval checkpoints
    pending_gate: Gate | None                # Waiting for human
    
    # Artifacts
    artifacts: dict[str, Artifact]           # Code, schemas, configs produced
    
    # Lineage
    decision_log: list[Decision]             # Every design decision with rationale
    review_log: list[Review]                 # Every builder review result
    
    # Status
    blocked_on: list[str]                    # What needs human input
    health: ProjectHealth                    # Summary metrics
```

**Storage:** JSON files on disk, one per project. Simple, inspectable, version-controllable.
The Nexus Connector's existing session persistence pattern extends naturally here.

---

### 2 — Constitution Enforcer

Loads the constitutional document stack and validates all agent outputs against it.

**Responsibilities:**
- Inject appropriate constitutional docs into every agent session context
- Validate Architect output against Doc 01 (Philosophy) and Doc 02 (Template) structure
- Validate Builder output against Doc 03 (Primitive Catalog) and Doc 04 (Contract Spec)
- Validate UX-related output against Doc 05 (Organic Decision UX)
- Flag violations before they enter the project state
- Maintain a violation log for human review

```python
class ConstitutionEnforcer:
    
    def __init__(self, doc_stack_path: str):
        """Load all constitutional documents."""
        self.docs = load_constitutional_stack(doc_stack_path)
    
    def build_architect_context(self, project: ProjectState) -> list[Message]:
        """
        Construct the Architect's session context.
        Includes: Doc 07 (Architect Constitution), Doc 01-06,
        current project state, and active task queue.
        """
        ...
    
    def build_builder_context(self, task: BuilderTask) -> list[Message]:
        """
        Construct a Builder's session context.
        Includes: Doc 00 (Session Preamble), relevant slice of Doc 02-05,
        and the specific Builder Task Contract. Nothing else.
        Builder cannot see full architecture or other tasks.
        """
        ...
    
    def validate_architect_output(self, output: str, project: ProjectState) -> ValidationResult:
        """
        Check Architect output for:
        - Correct template structure (Doc 02)
        - No vision-level decisions (scope boundary from Doc 07)
        - Fidelity ladder compliance (no tier skipping)
        - All verbs from catalog (Doc 03)
        """
        ...
    
    def validate_builder_output(self, output: str, task: BuilderTask) -> ValidationResult:
        """
        Check Builder output for:
        - Schema compliance (matches task contract)
        - Verb compliance (only catalog primitives)
        - Layer separation (state/rules/policy not mixed)
        - Constraint hardness (rejects, not warns)
        - Determinism (no uncontrolled randomness)
        - Scope compliance (didn't touch out-of-scope systems)
        """
        ...
```

**Implementation note:** Initial validation can be rule-based (regex, AST parsing for code,
schema matching for JSON). Later, a dedicated AI reviewer session can do semantic validation.
Start simple.

---

### 3 — Task Dispatch

Manages the lifecycle of Builder Tasks — creation, dispatch, monitoring, collection.

```python
class TaskDispatch:
    
    def __init__(self, nexus: NexusConnector):
        """Uses Nexus Connector for all AI communication."""
        self.nexus = nexus
    
    async def dispatch_task(self, task: BuilderTask, config: BuilderConfig) -> str:
        """
        1. Create a new Nexus session for the builder
        2. Inject constitutional context (via ConstitutionEnforcer)
        3. Inject the Builder Task Contract
        4. Execute the builder conversation
        5. Collect output artifacts
        6. Return session_id for tracking
        """
        ...
    
    async def collect_output(self, session_id: str) -> BuilderOutput:
        """
        Extract from completed builder session:
        - Code files produced
        - Schema definitions
        - Test results
        - Builder's notes/questions
        - Token usage
        """
        ...
```

**Builder isolation:** Each builder gets its own Nexus session. Builders cannot see each other's
work, the full architecture, or the project history. They see only their task contract and
the constitutional docs. This prevents cross-contamination and scope creep.

**Parallelism:** Independent tasks (different subsystems, same tier) can dispatch in parallel.
Dependent tasks must be sequenced. The Architect determines dependency order during
Phase 4 (Build Decomposition) of the Architect Constitution (Doc 07).

---

### 4 — Review Engine

The Architect reviews all builder output before it enters the project.

```python
class ReviewEngine:
    
    async def review(
        self,
        builder_output: BuilderOutput,
        task: BuilderTask,
        project: ProjectState,
        architect_session: str
    ) -> ReviewResult:
        """
        Review pipeline:
        1. Automated checks (Constitution Enforcer validation)
        2. Architect AI review (semantic check via Nexus session)
        3. Integration check (does this fit with existing components?)
        4. Produce verdict: accept | reject | revise | escalate
        """
        ...

class ReviewResult:
    verdict: Literal["accept", "reject", "revise", "escalate"]
    automated_checks: list[CheckResult]
    architect_notes: str
    integration_issues: list[str]
    revision_instructions: str | None    # If verdict is "revise"
    escalation_reason: str | None        # If verdict is "escalate" (needs human)
```

**Review flow:**
```
Builder output
  │
  ▼
Automated validation (Constitution Enforcer)
  │
  ├── FAIL → Reject with specific violation
  │
  ▼ PASS
Architect AI review (semantic)
  │
  ├── Issues found → Reject or Revise with instructions
  │
  ▼ PASS
Integration check
  │
  ├── Conflicts → Revise or Escalate to human
  │
  ▼ PASS
Accept → Merge into project artifacts
```

---

### 5 — Gate Manager

Controls approval checkpoints where the human reviews and decides.

```python
class Gate:
    gate_id: str
    gate_type: GateType          # design_review | tier_complete | scope_change | final
    trigger: str                 # What activates this gate
    status: Literal["pending", "approved", "rejected", "deferred"]
    
    # What the human sees
    summary: str                 # Architect's summary of what's ready for review
    artifacts: list[str]         # File paths to review
    decisions_made: list[Decision]  # Design decisions the Architect made
    questions: list[str]         # Architect's questions for the human
    
    # Human response
    human_response: str | None
    approved_at: datetime | None
    conditions: list[str]        # "Approved with these changes"

class GateType(Enum):
    VISION_CONFIRMED = "vision_confirmed"        # Vision Contract understood
    SYSTEM_DESIGN = "system_design"              # System decomposition approved
    DETAILED_DESIGN = "detailed_design"          # Full Architecture Template approved
    TIER_COMPLETE = "tier_complete"              # A fidelity tier is done
    SCOPE_CHANGE = "scope_change"               # Architect wants to change boundaries
    CONSTITUTIONAL_EXCEPTION = "constitutional"  # Architect wants to relax a rule
    FINAL_DELIVERY = "final"                    # Project complete
```

**Gate behavior:**
- When a gate activates, the orchestration engine **stops all work** on that project
- The human is notified with the gate summary, artifacts, and questions
- Nothing proceeds until the human responds: approve, reject, or approve-with-conditions
- Rejected gates return control to the Architect with feedback
- This is the human's primary control mechanism — you don't need to watch every step,
  just respond to gates

---

### 6 — Lineage Tracker

Every decision and artifact traces back to its origin.

```python
class Decision:
    decision_id: str
    timestamp: datetime
    made_by: Literal["human", "architect", "builder"]
    decision_type: str           # From escalation table in Doc 07
    description: str
    rationale: str
    vision_reference: str | None # Which part of Vision Contract motivated this
    constitutional_basis: str    # Which doc/section authorizes this decision
    
class Artifact:
    artifact_id: str
    file_path: str
    produced_by: str             # Task ID or "architect" or "human"
    task_id: str | None
    tier: int
    subsystem: str | None
    review_id: str               # Which review approved it
    lineage: list[str]           # Chain: vision → design decision → task → artifact
```

Any piece of code in the project can be traced: which builder wrote it, which task scoped it,
which Architect decision designed it, which part of the Vision Contract motivated it.

---

## Orchestration Workflow

### Full Lifecycle

```
Human fills Vision Contract (Doc 06)
  │
  ▼
Orchestration Engine creates project
  │
  ▼
Architect session starts (Nexus session with Doc 07 context)
  │
  ▼
Phase 1: Vision Intake
  Architect asks clarifying questions → Human answers
  ──► GATE: vision_confirmed
  │
  ▼
Phase 2: System Design
  Architect produces system decomposition, subsystem list, dependency map
  ──► GATE: system_design
  │
  ▼
Phase 3: Detailed Design
  Architect fills complete Architecture Template
  ──► GATE: detailed_design
  │
  ▼
Phase 4: Build Decomposition
  Architect creates ordered Builder Task Contracts
  │
  ▼
Phase 5: Build Supervision (per tier)
  │
  ├── For each task in current tier:
  │     │
  │     ├── Dispatch to Builder (new Nexus session)
  │     ├── Collect output
  │     ├── Automated validation
  │     ├── Architect review
  │     ├── Accept / Reject+Revise / Escalate
  │     └── Merge accepted artifacts
  │
  ├── Run integration sanity checks
  │
  └──► GATE: tier_complete (per tier)
  │
  ▼
Phase 6: Validation
  Full test suite, scenario runs, determinism checks
  ──► GATE: final_delivery
  │
  ▼
Project complete — all artifacts, docs, and lineage delivered
```

---

## Nexus Connector Integration

### What Already Exists (from current Nexus)

| Capability | Nexus Feature | Used For |
|-----------|---------------|----------|
| Multi-provider AI | `AIProvider` enum + connectors | Architect and Builders can use different providers |
| Persistent sessions | Session management | Architect maintains context across phases |
| Tool execution | `tool_executor.py` | Builders execute file operations |
| Stateful conversations | Conversation history | Architect remembers all design decisions |
| Autonomous execution | `auto_execute` + `max_iterations` | Builders work through multi-step tasks |
| Cost tracking | `cost_tracker.py` | Track spend per task, per tier, per project |

### What Needs to Be Added

```
nexus/
├── orchestration/
│   ├── engine.py              # Main orchestration loop
│   ├── project_state.py       # Project state model and persistence
│   ├── constitution.py        # Constitution enforcer
│   ├── task_dispatch.py       # Builder task lifecycle
│   ├── review_engine.py       # Automated + AI review pipeline
│   ├── gate_manager.py        # Approval gate logic
│   ├── lineage.py             # Decision and artifact tracking
│   └── models.py              # Shared data models
├── constitutional_docs/
│   ├── 00_session_preamble.md
│   ├── 01_simulation_philosophy.md
│   ├── 02_architecture_template.md
│   ├── 03_action_primitive_catalog.md
│   ├── 04_action_contract_spec.md
│   ├── 05_organic_decision_ux.md
│   ├── 06_vision_contract.md
│   └── 07_architect_constitution.md
├── core/                      # (existing)
├── connectors/                # (existing)
├── web/                       # (existing)
└── utils/                     # (existing)
```

### Engine Entry Point

```python
class OrchestrationEngine:
    
    def __init__(
        self,
        nexus_config: NexusConfig,
        constitution_path: str = "./constitutional_docs/",
        projects_path: str = "./projects/"
    ):
        self.nexus = NexusConnector(**nexus_config)
        self.constitution = ConstitutionEnforcer(constitution_path)
        self.dispatch = TaskDispatch(self.nexus)
        self.reviewer = ReviewEngine(self.nexus, self.constitution)
        self.gates = GateManager()
        self.lineage = LineageTracker()
        self.projects_path = projects_path
    
    async def new_project(self, vision: VisionContract) -> ProjectState:
        """
        Start a new project from a Vision Contract.
        Creates project state, initializes Architect session,
        begins Phase 1.
        """
        project = ProjectState(
            project_id=generate_id(),
            project_name=vision.project_name,
            vision_contract=vision,
            current_tier=0,
            current_phase=Phase.DESIGN
        )
        
        # Create Architect session with full constitutional context
        architect_context = self.constitution.build_architect_context(project)
        project.architect_session = await self.nexus.create_session(
            context=architect_context,
            provider=nexus_config.architect_provider
        )
        
        # Begin vision intake
        await self.run_phase_1(project)
        
        return project
    
    async def run_phase_1(self, project: ProjectState):
        """Vision intake — Architect asks clarifying questions."""
        response = await self.nexus.send_message(
            session=project.architect_session,
            message=f"Here is the Vision Contract:\n\n{project.vision_contract.to_markdown()}\n\n"
                    f"Review this vision. Ask any clarifying questions before proceeding to system design."
        )
        
        # Surface Architect's questions to human via gate
        self.gates.activate(Gate(
            gate_type=GateType.VISION_CONFIRMED,
            summary="Architect has reviewed the Vision Contract.",
            questions=extract_questions(response),
            artifacts=[]
        ))
    
    async def human_responds(self, project_id: str, gate_id: str, response: HumanResponse):
        """
        Handle human response to a gate.
        Routes back to appropriate phase.
        """
        project = self.load_project(project_id)
        gate = self.gates.resolve(gate_id, response)
        
        if gate.gate_type == GateType.VISION_CONFIRMED:
            # Forward human's answers to Architect, proceed to Phase 2
            await self.run_phase_2(project, response.message)
        
        elif gate.gate_type == GateType.SYSTEM_DESIGN:
            if response.approved:
                await self.run_phase_3(project)
            else:
                await self.revise_design(project, response.feedback)
        
        # ... similar routing for other gate types
    
    async def run_build_tier(self, project: ProjectState, tier: int):
        """
        Execute all builder tasks for a given fidelity tier.
        """
        project.current_tier = tier
        tasks = [t for t in project.task_queue if t.tier == tier]
        
        # Separate independent tasks (can parallelize) from dependent ones
        independent, dependent = partition_by_dependencies(tasks)
        
        # Dispatch independent tasks in parallel
        for task in independent:
            context = self.constitution.build_builder_context(task)
            session_id = await self.dispatch.dispatch_task(task, context)
            project.active_tasks[task.task_id] = (task, session_id)
        
        # Collect and review as they complete
        for task_id, (task, session_id) in project.active_tasks.items():
            output = await self.dispatch.collect_output(session_id)
            review = await self.reviewer.review(output, task, project)
            
            if review.verdict == "accept":
                project.artifacts.merge(output.artifacts)
                project.completed_tasks.append(CompletedTask(task, output, review))
            
            elif review.verdict == "revise":
                # Re-dispatch with revision instructions
                await self.dispatch.revise_task(session_id, review.revision_instructions)
            
            elif review.verdict == "escalate":
                # Surface to human
                self.gates.activate(Gate(
                    gate_type=GateType.SCOPE_CHANGE,
                    summary=review.escalation_reason
                ))
                return  # Pause until human responds
        
        # Tier complete
        self.gates.activate(Gate(
            gate_type=GateType.TIER_COMPLETE,
            summary=f"Tier {tier} complete. {len(tasks)} tasks finished.",
            artifacts=list(project.artifacts.keys())
        ))
```

---

## Provider Strategy

The Nexus Connector's multi-provider support creates interesting options:

| Role | Recommended Provider | Rationale |
|------|---------------------|-----------|
| Architect | Claude Opus / GPT-4o | Needs strong reasoning, design coherence |
| Builder (complex) | Claude Sonnet / GPT-4o | Code quality, instruction following |
| Builder (simple) | DeepSeek / local Ollama | Cost efficiency for routine tasks |
| Reviewer (automated) | Claude Haiku / GPT-4o-mini | Fast validation, lower cost |

The Architect can specify preferred providers per task type in the build plan.
The engine routes through the appropriate Nexus connector.

---

## Human Interface

### CLI Mode (Primary)

```bash
# Start a new project
nexus orchestrate new --vision ./my_vision.md

# Check project status
nexus orchestrate status --project my_project

# Respond to a pending gate
nexus orchestrate approve --project my_project --gate gate_003

# Reject with feedback
nexus orchestrate reject --project my_project --gate gate_003 \
    --feedback "Cooling system needs to model humidity, not just temperature"

# View lineage for an artifact
nexus orchestrate lineage --project my_project --artifact cooling_subsystem.py

# View decision log
nexus orchestrate decisions --project my_project

# View cost report
nexus orchestrate costs --project my_project
```

### Web Mode (Future)

Extend the existing Nexus `WebConnector` with orchestration endpoints:

```
POST   /projects                    Create project from Vision Contract
GET    /projects/{id}               Project status
GET    /projects/{id}/gates         Pending gates
POST   /projects/{id}/gates/{gid}   Respond to gate
GET    /projects/{id}/artifacts     List artifacts
GET    /projects/{id}/lineage       Decision and artifact lineage
GET    /projects/{id}/costs         Cost report
```

---

## File Structure Per Project

```
projects/
└── my_project/
    ├── project_state.json          # Full project state
    ├── vision_contract.md          # Human's original input
    ├── architecture_template.md    # Architect's filled template
    ├── subsystems/
    │   ├── power.md                # Subsystem one-pagers
    │   ├── cooling.md
    │   └── network.md
    ├── tasks/
    │   ├── task_001.json           # Task contracts + results
    │   ├── task_002.json
    │   └── task_003.json
    ├── artifacts/
    │   ├── src/                    # Builder-produced code
    │   ├── tests/                  # Builder-produced tests
    │   └── schemas/                # State schemas
    ├── reviews/
    │   ├── review_001.json         # Review results
    │   └── review_002.json
    ├── gates/
    │   ├── gate_001.json           # Gate records
    │   └── gate_002.json
    ├── lineage/
    │   ├── decisions.jsonl         # Decision log (append-only)
    │   └── artifacts.jsonl         # Artifact lineage (append-only)
    └── costs/
        └── usage.jsonl             # Token usage per session
```

---

## Build Order for the Orchestration Engine Itself

Following our own fidelity ladder:

### Tier 1 — State and Structure
- [ ] `ProjectState` model and JSON persistence
- [ ] `ConstitutionEnforcer` — doc loading and context building
- [ ] CLI: `new`, `status` commands

### Tier 2 — Dispatch and Collection
- [ ] `TaskDispatch` — create builder sessions, collect output
- [ ] Builder Task Contract generation from Architect output
- [ ] CLI: `dispatch`, `collect` commands

### Tier 3 — Gates
- [ ] `GateManager` — gate activation, human response routing
- [ ] CLI: `approve`, `reject` commands
- [ ] Workflow pauses correctly at gates

### Tier 4 — Review
- [ ] Automated validation (schema, verb, constraint checks)
- [ ] Architect AI review via Nexus session
- [ ] Accept / reject / revise / escalate flow

### Tier 5 — Full Workflow
- [ ] End-to-end orchestration loop (Phase 1–6)
- [ ] Parallel task dispatch for independent work
- [ ] Tier progression with gate checkpoints

### Tier 6 — Lineage and Observability
- [ ] Decision log
- [ ] Artifact lineage tracking
- [ ] Cost reporting
- [ ] CLI: `lineage`, `decisions`, `costs` commands

### Tier 7 — Web Interface
- [ ] FastAPI endpoints for project management
- [ ] Dashboard for gate management
- [ ] Real-time build progress

---

## Success Criteria

The orchestration engine is working if:

- You can write a Vision Contract in 10 minutes and walk away
- The Architect produces a coherent Architecture Template without drift
- Builders stay in scope and produce constitutional-compliant code
- Gates surface the right decisions at the right time
- You can trace any line of code back to the vision that motivated it
- The whole thing runs on your existing Nexus Connector infrastructure
- Swapping providers (for cost, speed, or capability) is a config change, not a rewrite
