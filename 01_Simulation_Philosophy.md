# Simulation Philosophy — Systems-Within-Systems Design

> Build the truth engine first. Layer intelligence and automation later.

This document defines how you think about simulation architecture.
Every design decision in this stack flows from these principles.

---

## 1 — Start With a Charter

Every simulation begins with a one-page contract. No exceptions.

**Define before writing code:**
- Purpose — what question does this sim answer?
- Scope boundary — what is inside the sim vs. external input?
- Resolution — what is one tick worth? (seconds, minutes, hours)
- Outputs — what does the user see? metrics, events, dashboards?
- Non-goals — what is explicitly not modeled?

A charter prevents scope creep. If it's not in the charter, it doesn't exist yet.

---

## 2 — Model Nested Systems, Not Feature Lists

The world is systems containing systems.

```
Domain System
 ├── Subsystem
 │    ├── Assets    (things that exist)
 │    ├── Flows     (what moves through)
 │    ├── State     (what changes)
 │    ├── Rules     (what must happen)
 │    ├── Limits    (what cannot be exceeded)
 │    └── Dependencies (what it relies on)
```

Each subsystem is a self-contained unit with a defined interface.
Never mix concerns across subsystem boundaries.

---

## 3 — Separate State, Rules, and Policy

This is the most important structural rule.

| Layer | Definition | Examples |
|-------|-----------|----------|
| **State** | What *is* | Inventories, capacities, conditions, topology |
| **Rules** | What *must happen* | Conservation laws, failure triggers, constraint checks |
| **Policy** | What *may be chosen* | Priority order, allocation strategy, operating modes |

State is fact. Rules are physics. Policy is tunable.

If you collapse these layers, the sim becomes unexplainable and untunable.

---

## 4 — The Engine Owns All Truth

The core simulation engine must be:
- **Deterministic** — same inputs produce same outputs
- **Rule-driven** — behavior comes from rules, not code paths
- **Constraint-enforcing** — invalid states are rejected, not warned
- **Auditable** — every transition is logged with cause
- **Replayable** — given a seed and inputs, reproduce any run

The engine owns state, resolves transitions, enforces constraints, and logs events.
Nothing else is allowed to invent reality.

---

## 5 — Model Flows Explicitly

Most complex systems are flow systems. If flows are implicit, behavior becomes unrealistic.

Every flow defines:
- Source and sink
- Rate and capacity
- Delay and loss
- Storage buffers
- Unserved / queued accounting

Flow types: energy, material, money, information, people, workload, risk.

If something moves through the system, it must be modeled as a flow with conservation.

---

## 6 — Constraints Are First-Class Objects

Constraints are not comments in code. They are tracked objects with state.

Each constraint has:
- What it limits (asset, system, flow)
- Limit value and current value
- Status (ok / warn / violated)
- Violation action (shed, queue, trip, reject)
- Human-readable explanation

A good sim can always answer: *"What is the limiting constraint right now?"*

---

## 7 — Dependencies Are a Graph

Systems fail and recover through dependency chains. Model them explicitly.

```
A depends on B for X
B depends on C for Y
```

Track: upstream requirements, downstream impacts, degradation states (not binary), fallback paths.

This enables cascade modeling and restoration logic — two things most sims handle poorly.

---

## 8 — Ordered Phases Per Tick

Each tick executes in a fixed phase order. Never allow random execution.

**Standard phase sequence:**
1. External inputs / scenario injections
2. Aging / degradation
3. Demand generation
4. Flow resolution
5. Constraint enforcement
6. Failure and protection rules
7. Control actions (operator/policy)
8. Recovery and restoration
9. Metrics, events, observability snapshot

This order preserves causality. Reordering phases changes outcomes.

---

## 9 — Design for Observability From Day One

If users cannot see inside the sim, they will not trust it.

**Minimum views:**
- Per-asset state and constraints
- Per-flow balances (supply vs. demand vs. unserved)
- Active constraints and which are binding
- Event timeline with cause chains
- Rejected actions and why

**Why-logs, not just event logs.** Every significant event records: what happened, why, which rule fired, what alternatives were rejected.

---

## 10 — Events Are First-Class

Use an event ledger, not just state deltas.

Each event records: trigger, timestamp, cause, affected assets, rule reference, severity, recovery conditions.

Events support replay, audit, training, and AI narration.

---

## 11 — Degradation Over Binary Failure

Avoid on/off states. Real systems degrade.

Prefer: normal → degraded → constrained → intermittent → capacity-reduced → offline.

Binary failure makes sims brittle and unrealistic. Degradation creates decision space.

---

## 12 — Recovery Is a System

Many sims model failure well and recovery poorly. Recovery requires:
- Repair capacity and crew limits
- Parts availability and lead times
- Restoration ordering (what comes back first?)
- Safety checks and staging requirements

Recovery is where the best player decisions happen. Model it with the same rigor as failure.

---

## 13 — Scenarios Make It a Laboratory

The scenario layer turns a sim into a research tool.

**Support:** scenario templates, event injection, parameter sweeps, seeded randomness, state snapshots, rewind/replay, A/B comparison.

Without a scenario engine, you have a demo. With one, you have a laboratory.

---

## 14 — Anchor to Reality

Even abstract sims need calibration. Use reference ranges, known ratios, empirical distributions, benchmark events, and sanity bounds.

Automated sanity checks catch impossible states early: conservation violations, negative inventories, queues exceeding physical capacity.

---

## 15 — Randomness With Discipline

Use randomness only where genuine uncertainty exists.

All randomness must be: seedable, bounded, domain-justified, logged, and replayable.

Never hide model flaws behind noise.

---

## 16 — AI Comes After Truth

If intelligence layers are added later, they must:
- Read state (never write it directly)
- Propose actions (never execute them)
- Be validated by the engine (never bypass rules)
- Be rejectable (never mandatory)

**Architecture pattern:** Deterministic Core + Advisory Intelligence Shell.

The engine is the source of truth. AI is a lens on that truth.

---

## 17 — Build in Fidelity Tiers

Do not start with maximum realism. Build in order:

| Tier | Focus | Content |
|------|-------|---------|
| 1 | Structure | Topology, assets, state schemas |
| 2 | Flows | Supply/demand, accounting, conservation |
| 3 | Constraints | Capacity, ramp, crew, budget limits |
| 4 | Failure | Faults, degradation, protection rules |
| 5 | Dependencies | Cascade engine, propagation, restoration |
| 6 | Operations | UX, scenarios, replay, experiments |
| 7 | Intelligence | AI advisors, optimization, autonomy |

Each tier must be solid before the next begins.

---

## 18 — Document the Model

Every subsystem needs: state schema, rule list, constraints, dependencies, update order, assumptions, and non-modeled factors.

Undocumented sims decay. If the AI can't read the spec, it can't build correctly.

---

## Core Test

A strong simulation is not built by adding features.
It is built by defining truth, enforcing rules, exposing constraints, modeling flows, logging causality, and layering complexity.

If you do that, any domain can sit on top of your engine.
