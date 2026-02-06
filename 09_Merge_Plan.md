# Merge Plan — Constitutional Orchestration Platform

Unifies three existing bodies of work into a single system:

- **Nexus Connector** — provider-agnostic AI communication, persistent sessions, tool execution
- **Multi-LLM Conductor** — proven multi-agent orchestration patterns, TDE, UAP, review loops
- **Constitutional Stack** — design methodology, architecture templates, verb catalogs, organic UX

This document maps what comes from where, what's new, and the build order.

---

## System Identity

**Name:** Nexus Orchestrator *(working title — Nexus handles communication, Orchestrator handles coordination)*

**One-line:** A constitutional multi-agent platform where an AI Architect manages AI Builders under human vision authority, with domain-aware validation and organic decision surfaces.

---

## What Comes From Where

### From Nexus Connector (Communication Layer)

| Component | Status | Role in New System |
|-----------|--------|-------------------|
| Provider-agnostic AI sessions | Existing | All agent communication routes through Nexus |
| `AIProvider` enum + connectors | Existing | Architect and Builders select providers per task |
| Persistent session management | Existing | Architect maintains context across phases |
| Tool execution engine | Existing | Builders execute file operations |
| `auto_execute` + `max_iterations` | Existing | Builder autonomous work loops |
| Cost tracking | Existing | Per-task, per-tier, per-project cost reporting |
| Streaming responses | Existing | Real-time progress for dashboard |
| Web integration (FastAPI) | Existing | Human interface for gates and monitoring |

**What changes:** Nexus becomes a dependency, not the application. The orchestration layer sits on top. Nexus sessions are created and managed by the orchestration engine, not directly by the user.

---

### From Multi-LLM Conductor (Proven Patterns)

| Component | Status | Role in New System |
|-----------|--------|-------------------|
| Task Decomposition Engine (TDE) | Existing (standalone) | Adapted to produce Builder Task Contracts |
| Universal Agent Protocol (UAP) | Existing (standalone) | Standardized agent interface beneath Nexus |
| V6 three-phase loop (analyze → review → implement) | Proven pattern | Maps to Builder → Architect Review → Revise cycle |
| V7 QA review with Claude API | Proven pattern | Becomes part of the Review Engine (constitutional + code quality) |
| File-based artifact exchange | Proven pattern | Primary artifact passing mechanism between agents |
| Non-interactive builder execution | Proven pattern | Builders never prompt humans; gates handle human input |
| Structured JSON output | Proven pattern | All builder output is machine-parseable |
| Session management across calls | Proven pattern | Architect session persists across all phases |
| DeepCoder CLI integration | Existing | Available as a builder provider option |
| Achievement/quality incentive system | Existing (UAP) | Optional quality scoring for builder output |

**Key lessons carried forward:**
- Simple, direct prompts work best → Builder Task Contracts are scoped and specific
- File-based communication is more reliable than stdout → Artifact exchange via filesystem
- Breaking complex tasks into smaller pieces improves success rates → Fidelity ladder + task decomposition
- No human interaction needed for execution → Humans interact at gates only

**What changes:** The Conductor's fixed pipeline (analyze → implement → validate → integrate) becomes a dynamic, Architect-driven decomposition. The TDE adapts to respect fidelity tiers and subsystem boundaries. The QA review expands to include constitutional validation, not just code quality.

---

### From Constitutional Stack (Design Authority)

| Document | Role in New System |
|----------|-------------------|
| 00 — Session Preamble | Injected into every builder session |
| 01 — Simulation Philosophy | Architect's internalized design principles |
| 02 — Architecture Template | Architect's primary output; project source of truth |
| 03 — Action Primitive Catalog | Verb validation for all builder output |
| 04 — Action Contract Spec | Execution boundary enforcement |
| 05 — Organic Decision UX | UX layer design rules |
| 06 — Vision Contract | Human's project input format |
| 07 — AI Architect Constitution | Architect's operating rules and authority boundaries |
| 08 — Orchestration Engine Spec | System architecture for the platform itself |

**What changes:** Documents become runtime configuration. The Constitution Enforcer loads them, injects relevant sections into session contexts, and validates output against them programmatically.

---

### New Components (Not in Any Existing System)

| Component | Purpose | Spec Reference |
|-----------|---------|---------------|
| Constitution Enforcer | Loads docs, builds agent contexts, validates output | Doc 08, §2 |
| Gate Manager | Structured human approval checkpoints | Doc 08, §5 |
| Lineage Tracker | Traces every artifact to its origin | Doc 08, §6 |
| Architect AI Role | Design authority agent with constitutional constraints | Doc 07 |
| Builder Task Contract Generator | Architect produces scoped task specs | Doc 07, Builder Task Contract |
| Decision Escalation Router | Routes decisions by authority level | Doc 07, Escalation Rules |
| Project State Store | Persistent project lifecycle state | Doc 08, §1 |
| Constitutional Validation Pipeline | Schema + verb + constraint + layer checks | Doc 08, §2 |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Human Interface                       │
│                                                           │
│  CLI: nexus-orch new/status/approve/reject/lineage/costs │
│  Web: FastAPI dashboard (gates, progress, artifacts)      │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────┐
│                  Orchestration Engine                      │
│                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Project      │ │ Gate         │ │ Lineage          │  │
│  │ State Store  │ │ Manager      │ │ Tracker          │  │
│  └──────────────┘ └──────────────┘ └──────────────────┘  │
│                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Constitution │ │ Task         │ │ Review           │  │
│  │ Enforcer     │ │ Decomposer   │ │ Engine           │  │
│  │              │ │ (from TDE)   │ │ (const + QA)     │  │
│  └──────────────┘ └──────────────┘ └──────────────────┘  │
│                                                           │
└───────┬──────────────────┬───────────────────┬───────────┘
        │                  │                   │
        ▼                  ▼                   ▼
┌──────────────┐  ┌──────────────┐    ┌──────────────┐
│ AI Architect │  │ AI Builder 1 │    │ AI Builder N │
│              │  │              │    │              │
│ Nexus Session│  │ Nexus Session│    │ Nexus Session│
│ + Doc 07     │  │ + Doc 00     │    │ + Doc 00     │
│ + Full Arch  │  │ + Task Only  │    │ + Task Only  │
└──────────────┘  └──────────────┘    └──────────────┘
        │                  │                   │
        ▼                  ▼                   ▼
┌──────────────────────────────────────────────────────────┐
│                    Nexus Connector                         │
│                                                           │
│  Provider-agnostic sessions, tool execution, streaming    │
│  OpenAI | Anthropic | Google | xAI | DeepSeek | Ollama   │
└──────────────────────────────────────────────────────────┘
```

---

## Component Mapping Detail

### Task Decomposer (TDE Adaptation)

**Source:** Conductor's Task Decomposition Engine
**Adaptation:** Instead of generic task breakdown, the decomposer now:

1. Receives the filled Architecture Template from the Architect
2. Respects fidelity tier ordering (Tier 1 tasks before Tier 2)
3. Respects subsystem boundaries (one subsystem per task, or explicitly cross-cutting)
4. Produces Builder Task Contracts (Doc 07 format) instead of generic task descriptions
5. Identifies parallelizable vs. dependent tasks from the dependency graph
6. Attaches relevant schema slices, verb lists, and constraint registries to each task

```python
class TaskDecomposer:
    """Adapted from Conductor TDE."""
    
    def decompose(
        self,
        architecture: ArchitectureTemplate,
        current_tier: int,
        constitution: ConstitutionEnforcer
    ) -> list[BuilderTaskContract]:
        """
        Break current tier's work into scoped builder tasks.
        
        1. Identify subsystems active in this tier
        2. For each subsystem, extract:
           - State schema slice
           - Relevant rules and policies
           - Applicable verb subset (from catalog)
           - Constraint objects
           - Interface definitions (what connects to what)
        3. Determine dependencies between tasks
        4. Sequence: independent tasks first (parallelizable),
           then dependent tasks in topological order
        5. Produce a BuilderTaskContract per task
        """
        ...
```

### Review Engine (V7 QA + Constitutional Validation)

**Source:** Conductor's V7 QA review + new constitutional checks
**Adaptation:** Two-stage review pipeline:

**Stage 1 — Constitutional Validation (Automated)**
Fast, rule-based checks. No AI needed.

| Check | Method | Source |
|-------|--------|--------|
| Schema compliance | AST parse + JSON schema match | Architecture Template §2 |
| Verb compliance | Regex/AST scan for function calls | Action Primitive Catalog |
| Constraint hardness | Pattern match for reject vs. warn | Action Contract Spec |
| Layer separation | Module/file structure analysis | Simulation Philosophy §3 |
| Determinism | Random usage audit (seeded only) | Philosophy §15 |
| Event logging | Presence of event ledger writes | Architecture Template §10 |
| Scope compliance | File/module boundary check | Builder Task Contract scope |

**Stage 2 — AI Review (Architect Session)**
Semantic validation via the Architect's Nexus session.

| Check | What It Catches |
|-------|----------------|
| Design coherence | Does this fit the overall architecture? |
| Interface correctness | Will this connect to adjacent subsystems? |
| Rule completeness | Are all specified rules implemented? |
| Constraint coverage | Are all relevant constraints enforced? |
| Code quality | Standard QA (from Conductor V7 pattern) |
| Test adequacy | Do tests cover the specified behavior? |

```python
class ReviewEngine:
    """Combines Conductor V7 QA + constitutional validation."""
    
    async def review(
        self,
        output: BuilderOutput,
        task: BuilderTaskContract,
        project: ProjectState
    ) -> ReviewResult:
        
        # Stage 1: Automated constitutional checks
        const_result = self.constitution.validate_builder_output(
            output.code_files,
            task,
            project.architecture
        )
        
        if const_result.has_violations:
            return ReviewResult(
                verdict="reject",
                reason=const_result.violations,
                stage="constitutional"
            )
        
        # Stage 2: Architect AI review (semantic)
        ai_review = await self.architect_review(output, task, project)
        
        # Stage 3: QA code quality (from Conductor V7 pattern)
        qa_review = await self.qa_review(output)
        
        return self.combine_verdicts(const_result, ai_review, qa_review)
```

### Agent Role Assignment

**Source:** Conductor's agent specialization + Nexus provider flexibility

| Role | Default Provider | Fallback | Rationale |
|------|-----------------|----------|-----------|
| Architect | Claude Opus | GPT-4o | Best reasoning for design decisions |
| Builder (complex subsystem) | Claude Sonnet | GPT-4o | Strong code quality |
| Builder (simple/routine) | DeepSeek | Ollama local | Cost efficiency (Conductor lesson: 90% cheaper) |
| Constitutional Validator | Rule-based (no AI) | — | Fast, deterministic, no cost |
| AI Reviewer | Claude Haiku | GPT-4o-mini | Fast semantic checks, low cost |
| QA Reviewer | Claude Haiku | DeepSeek | Code quality checks (from Conductor V7) |

The Architect can override provider assignments per task based on complexity assessment.

---

## File Structure

```
nexus-orchestrator/
├── nexus/                          # Nexus Connector (existing, as dependency)
│   ├── core/
│   ├── connectors/
│   ├── web/
│   └── utils/
│
├── orchestration/                  # New orchestration layer
│   ├── engine.py                   # Main orchestration loop
│   ├── project_state.py            # Project lifecycle state
│   ├── constitution.py             # Constitution enforcer
│   ├── task_decomposer.py          # Adapted from Conductor TDE
│   ├── task_dispatch.py            # Builder session management
│   ├── review_engine.py            # Constitutional + QA review
│   ├── gate_manager.py             # Human approval checkpoints
│   ├── lineage.py                  # Decision and artifact tracking
│   └── models.py                   # Shared data models
│
├── constitutional_docs/            # The document stack (runtime config)
│   ├── 00_session_preamble.md
│   ├── 01_simulation_philosophy.md
│   ├── 02_architecture_template.md
│   ├── 03_action_primitive_catalog.md
│   ├── 04_action_contract_spec.md
│   ├── 05_organic_decision_ux.md
│   ├── 06_vision_contract.md
│   └── 07_architect_constitution.md
│
├── cli/                            # Command-line interface
│   ├── main.py                     # CLI entry point
│   ├── commands/
│   │   ├── new.py                  # Create project from vision
│   │   ├── status.py               # Project status
│   │   ├── approve.py              # Approve gate
│   │   ├── reject.py               # Reject gate with feedback
│   │   ├── lineage.py              # Trace artifact origins
│   │   ├── costs.py                # Cost reporting
│   │   └── run.py                  # Manual dispatch commands
│   └── formatters.py               # CLI output formatting
│
├── web/                            # Web dashboard (extends Nexus web)
│   ├── app.py                      # FastAPI application
│   ├── routes/
│   │   ├── projects.py             # Project CRUD + status
│   │   ├── gates.py                # Gate management
│   │   ├── artifacts.py            # Artifact browsing
│   │   └── lineage.py              # Lineage visualization
│   ├── websocket.py                # Real-time progress updates
│   └── templates/                  # Dashboard UI (if server-rendered)
│
├── projects/                       # Per-project working directories
│   └── {project_id}/
│       ├── project_state.json
│       ├── vision_contract.md
│       ├── architecture_template.md
│       ├── subsystems/
│       ├── tasks/
│       ├── artifacts/
│       ├── reviews/
│       ├── gates/
│       ├── lineage/
│       └── costs/
│
├── config/
│   ├── providers.json              # API keys and provider preferences
│   ├── defaults.json               # Default settings
│   └── roles.json                  # Agent role → provider mapping
│
├── tests/
│   ├── test_constitution.py
│   ├── test_decomposer.py
│   ├── test_review.py
│   ├── test_gates.py
│   ├── test_lineage.py
│   └── test_integration.py
│
├── requirements.txt
├── setup.py
└── README.md
```

---

## Build Order

Following the fidelity ladder pattern, applied to the platform itself.

### Tier 1 — State and Skeleton (Week 1)

**Goal:** Project lifecycle exists. You can create a project, store state, and view status.

- [ ] `ProjectState` model and JSON persistence
- [ ] `ConstitutionEnforcer` — doc loading, context building for Architect and Builder roles
- [ ] Vision Contract parser (markdown → structured data)
- [ ] CLI: `nexus-orch new --vision ./vision.md`
- [ ] CLI: `nexus-orch status --project {id}`
- [ ] Basic test suite for state persistence

**Builds on:** Nothing. Fresh start with clean models.
**Validates with:** Create a project from a vision contract, inspect stored state.

---

### Tier 2 — Architect Session (Week 2)

**Goal:** The Architect AI can intake a vision, ask questions, and produce an Architecture Template.

- [ ] Architect session creation via Nexus (full constitutional context injected)
- [ ] Vision intake conversation (Phase 1 from Doc 07)
- [ ] Architecture Template generation (Phase 2-3 from Doc 07)
- [ ] Gate: `vision_confirmed` — pauses for human approval
- [ ] Gate: `system_design` — pauses for human approval
- [ ] CLI: `nexus-orch approve/reject --gate {id}`
- [ ] Architecture Template stored in project state

**Builds on:** Tier 1 state store + Nexus Connector sessions.
**Validates with:** Give Architect a vision contract, get back a coherent Architecture Template.

---

### Tier 3 — Task Decomposition (Week 3)

**Goal:** The Architect can break an approved architecture into Builder Task Contracts.

- [ ] `TaskDecomposer` — adapted from Conductor TDE
- [ ] Fidelity tier awareness (only decompose current tier)
- [ ] Subsystem boundary respect
- [ ] Dependency ordering (topological sort)
- [ ] Builder Task Contract generation (Doc 07 format)
- [ ] Relevant schema/verb/constraint slicing per task
- [ ] Task queue stored in project state

**Builds on:** Tier 2 Architecture Template output.
**Validates with:** Approved architecture → ordered list of scoped, constitutional task contracts.

---

### Tier 4 — Builder Dispatch and Collection (Week 4)

**Goal:** Builder tasks dispatch to AI sessions and produce artifacts.

- [ ] Builder session creation via Nexus (scoped context from Constitution Enforcer)
- [ ] Task dispatch — one Nexus session per task
- [ ] Artifact collection — code files, schemas, tests extracted from builder output
- [ ] File-based artifact exchange (Conductor pattern)
- [ ] Parallel dispatch for independent tasks
- [ ] Sequential dispatch for dependent tasks
- [ ] Cost tracking per task

**Builds on:** Tier 3 task contracts + Nexus Connector sessions.
**Validates with:** Dispatch a builder task, collect working code that matches the task contract.

---

### Tier 5 — Review Pipeline (Week 5)

**Goal:** All builder output is validated before entering the project.

- [ ] Stage 1: Automated constitutional validation
  - [ ] Schema compliance checker
  - [ ] Verb compliance scanner
  - [ ] Constraint hardness checker
  - [ ] Layer separation checker
  - [ ] Scope compliance checker
- [ ] Stage 2: Architect AI review (via Nexus session)
- [ ] Stage 3: QA code quality review (Conductor V7 pattern)
- [ ] Accept / Reject / Revise / Escalate flow
- [ ] Revision dispatch (rejected tasks re-sent with feedback)
- [ ] Gate: `tier_complete` at each fidelity tier boundary

**Builds on:** Tier 4 builder output + Constitution Enforcer.
**Validates with:** Submit builder output with intentional violations — verify they're caught.

---

### Tier 6 — Full Workflow Loop (Week 6)

**Goal:** End-to-end orchestration from vision to completed tier.

- [ ] Complete Phase 1–5 workflow (Doc 07)
- [ ] Tier progression with gates
- [ ] Architect manages multiple builder tasks per tier
- [ ] Integration sanity checks after merging artifacts
- [ ] Project health metrics
- [ ] CLI: full command set operational

**Builds on:** All previous tiers.
**Validates with:** Vision contract in → working Tier 3 simulation out, with full lineage.

---

### Tier 7 — Lineage and Observability (Week 7)

**Goal:** Every decision and artifact is traceable. Full visibility into the build process.

- [ ] Decision log (append-only JSONL)
- [ ] Artifact lineage (vision → design decision → task → artifact chain)
- [ ] Cost reporting (per task, per tier, per project, per provider)
- [ ] CLI: `nexus-orch lineage`, `nexus-orch decisions`, `nexus-orch costs`
- [ ] Export capability (full project archive)

**Builds on:** Tier 6 running workflow.
**Validates with:** Pick any artifact, trace it back to the vision contract.

---

### Tier 8 — Web Dashboard (Week 8+)

**Goal:** Visual interface for project management, gate approval, and monitoring.

- [ ] FastAPI routes for projects, gates, artifacts, lineage
- [ ] WebSocket real-time progress (Conductor dashboard pattern)
- [ ] Gate approval/rejection UI
- [ ] Tier progress visualization
- [ ] Artifact browser
- [ ] Lineage graph visualization
- [ ] Cost dashboard

**Builds on:** All previous tiers + Nexus web integration.
**Validates with:** Manage an entire project lifecycle through the browser.

---

## Migration Considerations

### From Conductor Codebase

| Component | Action |
|-----------|--------|
| TDE logic | Extract decomposition algorithm, adapt to produce Builder Task Contracts |
| V7 QA reviewer | Extract Claude API QA logic, integrate as Stage 3 of Review Engine |
| DeepCoder CLI integration | Available as builder provider via Nexus Ollama/DeepSeek connector |
| UAP framework | Evaluate whether Nexus connector abstraction supersedes it, or if UAP adds value as a sub-layer |
| AOS visual designer | Defer to Tier 8; dashboard may serve this purpose differently |
| Achievement system | Optional quality scoring; can plug into Review Engine metrics |
| File-based communication pattern | Adopt as primary artifact exchange mechanism |
| Session management | Nexus handles this natively |

### From Nexus Connector Codebase

| Component | Action |
|-----------|--------|
| All connectors | Use as-is; orchestration layer creates sessions through Nexus |
| Web connector / FastAPI | Extend with orchestration routes |
| Session manager | Use as-is for agent session lifecycle |
| Cost tracker | Extend with per-task and per-project aggregation |
| Tool executor | Use as-is for builder file operations |
| GM Connector | Not needed for orchestration; remains available for game projects |

### New Code

| Component | Estimated Effort | Dependencies |
|-----------|-----------------|--------------|
| `ProjectState` + persistence | Small | None |
| `ConstitutionEnforcer` | Medium | Doc stack finalized |
| `TaskDecomposer` | Medium | TDE extraction + adaptation |
| `TaskDispatch` | Medium | Nexus sessions |
| `ReviewEngine` | Large | Constitution Enforcer + QA extraction |
| `GateManager` | Medium | Project State |
| `LineageTracker` | Medium | Project State |
| `OrchestrationEngine` (main loop) | Large | All above |
| CLI commands | Medium | Engine + State |
| Web routes | Medium | Engine + Nexus web |

---

## Success Criteria

The platform is working if:

1. **Vision to architecture in one session** — hand it a Vision Contract, get back a coherent Architecture Template without drift
2. **Constitutional compliance** — builder output that violates the verb catalog, schema spec, or layer separation is automatically caught and rejected
3. **Gate control works** — you can walk away after submitting a vision and come back to approve gates at your own pace
4. **Lineage is complete** — any line of code traces back through: builder task → Architect decision → Architecture Template section → Vision Contract element
5. **Provider flexibility** — swapping the Architect from Claude to GPT-4o, or a builder from Sonnet to DeepSeek, is a config change
6. **Cost efficiency** — routine builder tasks run on cheap providers; expensive models reserved for Architect and complex work
7. **It uses what you already built** — Nexus sessions, Conductor patterns, constitutional docs are all load-bearing, not rewritten

---

## What This Enables

Once the platform works for simulation building (the first constitutional domain), adding new domains means:

1. Write a new constitutional doc stack for that domain (equivalent of Docs 01–05)
2. Drop it in `constitutional_docs/`
3. The same Architect + Builder + Review pipeline enforces the new domain's rules

The orchestration engine is domain-agnostic. The constitutional docs make it domain-specific.
That's the pattern: **one engine, many constitutions.**
