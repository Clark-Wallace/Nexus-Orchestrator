# Nexus Orchestrator

**Constitutional multi-agent engineering — the Unified Framework made executable.**

Nexus Orchestrator is a platform where an AI Architect manages AI Builders under human vision authority, governed by domain-specific constitutional documents. It turns the principles of signal integrity, progressive capability, and human authority into an enforceable runtime for building complex systems with AI.

Built on the philosophical foundation of the **Rose Model** (`Meaning = Signal × Context`), the **Unified Framework for Human-AI Systems**, and proven patterns from the **Nexus Connector** and **Multi-LLM Conductor** projects.

---

## The Problem

AI is good at building things. AI is bad at staying disciplined across sessions.

If you're an architect-level engineer using AI to build complex systems, you've hit these walls:

- **Drift.** The AI builds something coherent in one session, then contradicts it in the next.
- **Invention.** The AI adds mechanics, patterns, or capabilities you didn't ask for and don't want.
- **Layer collapse.** Clean architectural separations dissolve as the AI takes shortcuts.
- **Loss of control.** You spend more time correcting the AI than building.
- **No memory.** Every session starts from zero. Design decisions don't persist.

Multi-agent frameworks exist (CrewAI, AutoGen, LangGraph), but they solve agent *communication*. They don't solve agent *governance* — how do you keep AI architecturally disciplined, enforce domain-specific design rules, and give the human structured control without micromanaging?

---

## The Solution

Nexus Orchestrator introduces **constitutional engineering** — a methodology where:

1. **Domain rules are documents, not code.** A stack of markdown files defines what the AI can and cannot do, what patterns it must follow, and what authority it has. These docs are loaded at runtime and injected into every agent session.

2. **An AI Architect has design authority, not vision authority.** It expands your sparse creative brief into a full architecture, decomposes work into scoped tasks, and reviews all builder output — but it cannot change your goals, skip your approval, or violate the constitutional docs.

3. **AI Builders are scoped and isolated.** Each builder sees only its task contract and the constitutional rules. It cannot see other builders' work, the full architecture, or the project history. This prevents cross-contamination and scope creep.

4. **Humans control through gates, not micromanagement.** You approve design milestones, not individual lines of code. Walk away after submitting a vision. Come back when the system needs a decision.

5. **Everything traces back to the vision.** Every artifact, every design decision, every line of code has a lineage chain: Vision Contract → Architecture Template → Builder Task → Code.

---

## How It Maps to the Unified Framework

Nexus Orchestrator is the executable implementation of the [Unified Framework for Human-AI Systems](docs/UNIFIED_FRAMEWORK.md). Every component traces to a framework principle:

| Unified Framework Principle | Nexus Orchestrator Implementation |
|---|---|
| **Rose Model** — Meaning = Signal × Context | Constitutional docs (signal integrity) + project state (context) = coherent systems |
| **Law 1: Foundation First** | Fidelity ladder — structure before flows, flows before intelligence |
| **Law 2: Graceful Degradation** | Constraint supremacy — if AI fails, engine rules still hold |
| **Law 3: Human Authority** | Gate-controlled workflow — humans approve, AI proposes |
| **Law 4: Meaningful Support** | Organic Decision UX — AI surfaces options, humans decide |
| **L0–L4 Capability Spectrum** | Build tiers 1–7, AI integration only at Tier 7 |
| **CLI-First Development (D0→D3)** | CLI commands first, web dashboard later |
| **Creative Symbiosis (Spark & Forge)** | Vision Contract (spark) → Architect + Builders (forge) |
| **Signal & Context Intelligence** | Information imperfection — truth state vs. observed vs. narrated |
| **CI Negotiation Loop** | Action Contract validation — propose, validate, accept/reject/revise |
| **Wisdom Chain** | Lineage tracker — decisions and artifacts persist across sessions |
| **CPMAI Signal-Aware Phases** | Gate-controlled phases with tier progression |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Human (Vision)                        │
│                                                           │
│  "Build a data center operations sim"                     │
│  "Make a power grid training tool"                        │
│  "Create an emergency management simulator"               │
│                                                           │
│  Approves at gates. Doesn't micromanage.                  │
└────────────────────────┬─────────────────────────────────┘
                         │ Vision Contract
                         ▼
┌──────────────────────────────────────────────────────────┐
│                  Orchestration Engine                      │
│                                                           │
│  Project State │ Gate Manager │ Lineage Tracker           │
│  Constitution Enforcer │ Task Decomposer │ Review Engine  │
└───────┬──────────────────┬───────────────────┬───────────┘
        │                  │                   │
        ▼                  ▼                   ▼
┌──────────────┐  ┌──────────────┐    ┌──────────────┐
│ AI Architect │  │ AI Builder 1 │    │ AI Builder N │
│ Design auth. │  │ Scoped task  │    │ Scoped task  │
│ Full context │  │ Task only    │    │ Task only    │
└──────────────┘  └──────────────┘    └──────────────┘
        │                  │                   │
        ▼                  ▼                   ▼
┌──────────────────────────────────────────────────────────┐
│                    Nexus Connector                         │
│  Provider-agnostic AI sessions                            │
│  OpenAI │ Anthropic │ Google │ xAI │ DeepSeek │ Ollama   │
└──────────────────────────────────────────────────────────┘
```

---

## Constitutional Document Stack

The constitutional docs are the core innovation. They're markdown files that define domain-specific rules for AI behavior — loaded at runtime, injected into agent contexts, validated against programmatically.

### Framework-Level Docs (Apply to All Domains)

| Doc | Purpose |
|-----|---------|
| `00_Session_Preamble.md` | Orients any AI at session start — role, constraints, failure modes |
| `06_Vision_Contract.md` | Human's sparse creative input — the spark |
| `07_AI_Architect_Constitution.md` | Architect's authority boundaries, workflow, escalation rules |
| `08_Orchestration_Engine_Spec.md` | Platform architecture and component design |
| `09_Merge_Plan.md` | Integration plan for Nexus + Conductor + constitutional stack |

### Domain Docs: Systems Simulation (First Domain Module)

| Doc | Purpose |
|-----|---------|
| `01_Simulation_Philosophy.md` | How to think about simulation design — 18 principles |
| `02_Architecture_Template.md` | Fillable blueprint — state schemas, flows, constraints, phases |
| `03_Action_Primitive_Catalog.md` | Complete typed verb set — the only legal simulation mutations |
| `04_Action_Contract_Spec.md` | Boundary between AI-composed decisions and engine execution |
| `05_Organic_Decision_UX.md` | How decisions surface from constraints, not scripts |

**To add a new domain:** Write docs 01–05 for that domain. Drop them in. Same engine, same Architect, same workflow — different rules.

---

## The Workflow

```
1. You write a Vision Contract (10 minutes)
   "Build a data center operations sim for NOC operator training"

2. Architect intakes your vision, asks clarifying questions
   ──► GATE: You confirm the vision is understood

3. Architect produces system decomposition and architecture
   ──► GATE: You approve the design

4. Architect decomposes into scoped Builder Task Contracts
   Following the fidelity ladder: structure → flows → constraints → failure → dependencies → UX

5. Builders execute tasks in isolated sessions
   Each builder sees only its task + constitutional rules

6. Review pipeline validates all output
   Stage 1: Automated constitutional checks (schema, verbs, constraints, layer separation)
   Stage 2: Architect AI review (semantic coherence)
   Stage 3: QA code quality review

7. Accepted artifacts merge into the project
   ──► GATE: You review at each tier completion

8. Repeat until the fidelity target is reached
```

---

## CLI Usage

```bash
# Create a new project from a Vision Contract
nexus-orch new --vision ./my_vision.md

# Check project status
nexus-orch status --project my_project

# Respond to a pending gate
nexus-orch approve --project my_project --gate gate_003
nexus-orch reject --project my_project --gate gate_003 \
    --feedback "Cooling system needs humidity modeling"

# Trace an artifact back to its origin
nexus-orch lineage --project my_project --artifact cooling_subsystem.py

# View all design decisions
nexus-orch decisions --project my_project

# Cost report
nexus-orch costs --project my_project
```

---

## Key Concepts

### Constitutional Engineering

Rules for AI behavior expressed as documents, not code. The AI reads them, internalizes them, and the system validates output against them. If a verb isn't in the catalog, it doesn't exist. If a constraint is violated, the action is rejected. If a builder touches something outside its task scope, the review catches it.

### Organic Decision UX

Decisions are never prewritten. They're constructed at runtime from system state:

```
STATE + CONSTRAINTS + ACTION VERBS → DECISION SPACE
```

No A/B/C menus. No scripted choice trees. The AI moderator translates the decision space into human-usable form. If you remove all prewritten decisions and the system still produces meaningful choices, the model is organic.

### Fidelity Ladder

Complex systems are built in tiers, not all at once:

| Tier | Focus |
|------|-------|
| 1 | Structure — topology, assets, state schemas |
| 2 | Flows — supply/demand, accounting, conservation |
| 3 | Constraints — capacity, ramp, crew, budget limits |
| 4 | Failure — faults, degradation, protection rules |
| 5 | Dependencies — cascade engine, propagation, restoration |
| 6 | Operations — UX, scenarios, replay, experiments |
| 7 | Intelligence — AI advisors, optimization, autonomy |

Each tier must be solid before the next begins. The Architect enforces this.

### The Four Laws (from the Unified Framework)

1. **Foundation First.** Build what works without AI before adding AI.
2. **Graceful Degradation.** Every layer falls back to the layer below.
3. **Human Authority.** Humans provide vision and judgment. AI provides speed and exploration.
4. **Meaningful Support.** AI supports meaningful human work — it doesn't replace it.

---

## Provider Flexibility

The Nexus Connector makes the platform provider-agnostic. Assign the right model to the right job:

| Role | Recommended | Fallback | Why |
|------|------------|----------|-----|
| Architect | Claude Opus | GPT-4o | Best reasoning for design |
| Builder (complex) | Claude Sonnet | GPT-4o | Strong code quality |
| Builder (routine) | DeepSeek | Ollama local | 90% cost reduction |
| Reviewer | Claude Haiku | GPT-4o-mini | Fast, cheap validation |

Swapping providers is a config change, not a rewrite.

---

## Project Structure

```
nexus-orchestrator/
├── constitutional_docs/          # Domain rule stacks (runtime config)
│   ├── simulation/               # First domain module
│   │   ├── 01_simulation_philosophy.md
│   │   ├── 02_architecture_template.md
│   │   ├── 03_action_primitive_catalog.md
│   │   ├── 04_action_contract_spec.md
│   │   └── 05_organic_decision_ux.md
│   └── _framework/               # Domain-agnostic docs
│       ├── 00_session_preamble.md
│       ├── 06_vision_contract.md
│       └── 07_architect_constitution.md
│
├── nexus/                        # Communication layer (Nexus Connector)
│   ├── core/
│   ├── connectors/
│   └── web/
│
├── orchestration/                # Coordination layer
│   ├── engine.py
│   ├── project_state.py
│   ├── constitution.py
│   ├── task_decomposer.py
│   ├── task_dispatch.py
│   ├── review_engine.py
│   ├── gate_manager.py
│   └── lineage.py
│
├── cli/                          # Human interface
│   └── commands/
│
├── web/                          # Dashboard (future)
│   └── routes/
│
├── projects/                     # Per-project state and artifacts
├── docs/                         # Framework documentation
│   └── UNIFIED_FRAMEWORK.md
├── tests/
├── README.md
└── LICENSE
```

---

## Lineage

This project converges three bodies of prior work:

**Nexus Connector** — Provider-agnostic AI communication. Persistent sessions, tool execution, streaming, cost tracking. Becomes the communication layer.

**Multi-LLM Conductor** — Proven multi-agent orchestration. Task Decomposition Engine, Universal Agent Protocol, V6/V7 review loops, file-based artifact exchange. Provides the proven mechanics.

**Unified Framework for Human-AI Systems** — The Rose Model, Creative Symbiosis, AI Integration Spectrum (L0–L4), CLI-first development, CPMAI, Wisdom Chain. Provides the philosophical foundation and architectural principles.

The constitutional document stack is the bridge — framework principles expressed as enforceable AI governance rules.

---

## Roadmap

### Phase 1: Constitutional Docs (Available Now)
The document stack is usable today with any AI tool. Load the docs into a Claude or ChatGPT session and they constrain behavior immediately. No engine required.

### Phase 2: Orchestration Engine (Building)
Project state, Architect sessions, task decomposition, builder dispatch, review pipeline, gates, lineage. Builds on Nexus Connector infrastructure.

### Phase 3: Domain Expansion
New constitutional doc stacks for additional domains — data pipeline design, technical documentation, hardware project management, enterprise resource planning. Same engine, different rules.

### Phase 4: Web Dashboard
Visual project management, gate approval UI, tier progress, lineage graphs, cost dashboards. Extends Nexus web integration.

---

## Getting Started

### Use the Docs Today (No Engine Required)

The constitutional docs work standalone. Copy the relevant docs into any AI session:

1. Start with `00_Session_Preamble.md` — orients the AI
2. Add the domain docs (01–05) for your domain
3. Fill out `06_Vision_Contract.md` for your project
4. The AI now operates under constitutional constraints

This is how the framework was developed and tested. The engine automates what you can do manually today.

### Run the Engine (Coming Soon)

```bash
# Install
git clone https://github.com/Clark-Wallace/nexus-orchestrator.git
cd nexus-orchestrator
pip install -e .

# Configure providers
cp config/providers.example.json config/providers.json
# Add your API keys

# Create a project
nexus-orch new --vision ./my_vision.md

# Check status
nexus-orch status

# Approve gates as they appear
nexus-orch approve --gate gate_001
```

---

## Philosophy

> Build systems where meaning compounds — where signal integrity is preserved, context is continuously aligned, and both human and AI contribute what they do best.

The AI is not the architect. The AI is not the visionary. The AI is a disciplined collaborator operating under explicit rules, building what the human designed, validated at every step.

**One engine. Many constitutions. Human authority preserved.**

---

## License

MIT

---

## Author

**Clark Wallace**
Senior Chief Petty Officer, U.S. Navy
Systems thinker. Framework builder. Architect-level vibe coder.

*"You are not managing code. You are orchestrating intelligence."*
