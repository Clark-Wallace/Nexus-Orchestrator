# Simulation Architecture Template

A working blueprint for systems-within-systems simulations.
Fill this out per project. The AI uses this as the source of truth for what exists and what doesn't.

---

## Build State

**Current Tier:** ___  
*(1=Structure, 2=Flows, 3=Constraints, 4=Failure, 5=Dependencies, 6=Operations, 7=Intelligence)*

**Last Updated:** ___

---

## 0 — Charter

**Purpose:** [ ] Training / [ ] Planning / [ ] Research / [ ] Digital Twin / [ ] Game / [ ] Forecasting

**Primary Questions**
1. ___
2. ___
3. ___

**Scope**
- Inside sim: ___
- External inputs: ___

**Time**
- Tick size: ___
- Run horizon: ___
- Determinism: [ ] Fully deterministic / [ ] Seeded randomness

**Outputs:** ___

**Non-goals (explicitly not modeled):** ___

---

## 1 — System Decomposition

### 1.1 Domain Systems
| ID | System | Purpose |
|----|--------|---------|
| S1 | | |
| S2 | | |
| S3 | | |

### 1.2 Subsystems
| Parent | ID | Subsystem | Assets | Primary Flows |
|--------|----|-----------|--------|---------------|
| S1 | S1-A | | | |
| S1 | S1-B | | | |

### 1.3 Cross-System Dependencies
| Source | Depends On | For |
|--------|-----------|-----|
| S1 | S2 | |
| S3 | S1 | |

---

## 2 — State Model

### 2.1 Global State Container
```
world_state
 ├── meta          (sim identity, config)
 ├── time          (tick, clock, phase)
 ├── systems{}     (per-system state trees)
 ├── signals{}     (cross-system coupling values)
 ├── events[]      (event ledger)
 └── metrics{}     (global KPIs)
```

### 2.2 Subsystem State Schema
For each subsystem X:

```
X
 ├── assets[]      (things that exist)
 │    ├── asset_id: string
 │    ├── type: enum
 │    ├── location: node_id
 │    ├── capacity: float
 │    ├── condition: float [0.0, 1.0]
 │    ├── mode: enum [normal, degraded, reduced, offline, standby]
 │    └── dependencies: asset_id[]
 ├── state{}       (mutable variables)
 ├── flows{}       (movement accounting)
 ├── constraints[] (active limits — see §6)
 ├── policy{}      (tunable knobs — see §3.2)
 ├── metrics{}     (subsystem KPIs)
 └── event_log[]   (local events)
```

---

## 3 — Rules and Policy

### 3.1 Rule Template
```
rule_id:            string
trigger:            condition expression
preconditions:      state requirements
action:             state mutation
constraints_checked: constraint_id[]
outputs:            event_type[]
```

### 3.2 Policy Template
```
policy_id:          string
objective:          what it optimizes for
allowed_actions:    primitive_verb[]     (from Action Catalog)
priority_order:     entity_id[]
tunable_knobs:      parameter: range[]
safety_bounds:      hard limits
```

Rules execute automatically. Policies are chosen. Never mix them.

---

## 4 — Time Engine

### 4.1 Tick Contract
Every tick is: deterministic, ordered, auditable, optionally reversible.

### 4.2 Phase Order
| Phase | Purpose |
|-------|---------|
| 1 | External inputs / scenario injections |
| 2 | Aging / degradation |
| 3 | Demand generation |
| 4 | Flow resolution |
| 5 | Constraint enforcement |
| 6 | Failure and protection rules |
| 7 | Control actions (operator/policy) |
| 8 | Recovery and restoration |
| 9 | Metrics + events + observability snapshot |

### 4.3 Subsystem Interface
Each subsystem exposes:
- `init(world_state, config) → void`
- `step(world_state, tick_ctx) → state_delta`
- `report(world_state) → metrics`

---

## 5 — Flows

### 5.1 Flow Schema
```
flow_id:        string
type:           enum [resource, people, money, info, risk]
sources:        node_id[]
sinks:          node_id[]
rate:           float
capacity:       float
delay:          ticks
loss:           float [0.0, 1.0]
buffers:        {node_id: buffer_capacity}
unserved:       float       (demand minus supply)
queued:         float       (waiting for capacity)
```

### 5.2 Conservation Rule
For every flow: `sum(inflows) - sum(outflows) - losses = Δstorage`

If this doesn't balance, something is wrong.

---

## 6 — Constraints Registry

### 6.1 Constraint Object
```
constraint_id:      string
applies_to:         entity_id
type:               enum [capacity, timing, ramp, resource, crew, budget, physics, policy]
limit_value:        float
current_value:      float
headroom:           float       (limit - current)
status:             enum [ok, warn, binding, violated]
violation_action:   enum [shed, queue, trip, reject, degrade]
explain:            string      (human-readable)
```

### 6.2 Pressure Detection
A constraint becomes a **pressure** when:
- `headroom < threshold` (approaching limit)
- `status == binding` (at limit)
- `status == violated` (past limit — action required)

Pressures feed the Organic Decision UX. See Document 05.

---

## 7 — Dependencies and Cascades

### 7.1 Dependency Edge
```
source:             entity_id
depends_on:         entity_id
for:                resource_type
criticality:        enum [required, degraded_without, optional]
fallback:           entity_id | null
```

### 7.2 Degradation States
```
normal → degraded → capacity_reduced → intermittent → offline
```
Each state has defined capability percentages. Avoid binary on/off.

### 7.3 Cascade Rule
```
cascade_id:         string
trigger:            dependency failure condition
propagation:        enum [degrade, cap, disable]
affected:           entity_id[]
recovery_condition: state expression
priority_class:     int
```

---

## 8 — Failure and Recovery

### 8.1 Failure Models
| Type | Trigger | Example |
|------|---------|---------|
| Random | Seeded probability per tick | Pipe burst |
| Condition | Health threshold crossed | Transformer aging |
| Event | Scenario injection | Storm damage |
| Correlated | Zone-based field | Regional weather |

### 8.2 Recovery Model
```
repair_crew_capacity:   int
parts_inventory:        {part_type: count}
lead_times:             {part_type: ticks}
restoration_order:      entity_id[]     (priority sequence)
safety_checks:          bool            (adds delay)
staged_recovery:        phase_sequence[]
```

---

## 9 — Observability

### 9.1 Required Views
- System dashboard (KPIs + trends)
- Asset inspector (state + constraints + dependencies)
- Event timeline (what + why + cause chain)
- Constraint monitor (which limits are binding)
- Unserved ledger (where demand is unmet)

### 9.2 Why-Log Template
```
what:                   event description
when:                   tick
trigger:                condition that fired
rule:                   rule_id
constraint_violated:    constraint_id | null
upstream_causes:        event_id[]
downstream_impacts:     entity_id[]
rejected_alternatives:  action[]
prevention:             what would have avoided this
```

---

## 10 — Event Ledger

### 10.1 Event Object
```
event_id:           string
tick:               int
event_type:         enum
severity:           enum [info, warning, critical, emergency]
entities_affected:  entity_id[]
cause_chain:        event_id[]
rule_id:            string
metrics_delta:      {metric: delta}
notes:              string
```

### 10.2 Replay
- Deterministic seed stored per run
- Snapshots every N ticks (configurable)
- Event stream exportable as JSON

---

## 11 — Scenario Engine

### 11.1 Scenario Template
```
name:               string
initial_conditions: state overrides
injected_events:    [{tick, event_type, target, intensity}]
toggled_policies:   {policy_id: setting}
eval_metrics:       metric_id[]
termination:        condition | max_ticks
```

### 11.2 Experiment Modes
- Single run
- Batch parameter sweeps
- Monte Carlo (seeded)
- A/B comparison (same seed, different policy)

---

## 12 — Calibration

### 12.1 Targets
- Baseline ranges for key metrics
- Known ratio checks (e.g., demand/capacity)
- Historical event replay (if available)

### 12.2 Automated Sanity Checks
- [ ] Conservation balanced for all flows
- [ ] No negative inventories
- [ ] No queues exceeding physical capacity
- [ ] No impossible state combinations
- [ ] Monotonic constraints hold (e.g., demand ≥ 0)

---

## 13 — AI Integration (Tier 7 Only)

**Rule:** AI cannot bypass the authoritative core.

| Level | Role | Authority |
|-------|------|-----------|
| L1 | Observer | Read state, forecast, explain |
| L2 | Advisor | Recommend actions to user |
| L3 | Controller | Execute within bounded policy |
| L4 | Autonomous | Supervised self-direction |

**Guardrail:** AI proposes → Engine validates → Approved or rejected with reason.

---

## 14 — Build Checklist

| Tier | Item | Status |
|------|------|--------|
| 1 | Charter written | [ ] |
| 1 | Systems/subsystems listed | [ ] |
| 1 | State schemas defined | [ ] |
| 2 | Flow accounting implemented | [ ] |
| 2 | Conservation checks passing | [ ] |
| 3 | Constraints registry implemented | [ ] |
| 3 | Pressure detection working | [ ] |
| 4 | Failure models implemented | [ ] |
| 4 | Recovery models implemented | [ ] |
| 5 | Dependency graph implemented | [ ] |
| 5 | Cascade rules working | [ ] |
| 6 | Observability views exist | [ ] |
| 6 | Scenario engine exists | [ ] |
| 6 | Replay working | [ ] |
| 7 | AI integration (if applicable) | [ ] |

---

## Appendix — Subsystem One-Pager Template

```
Subsystem:          ___
Purpose:            ___
Parent System:      ___
Assets:             ___
State Variables:    ___
Flows:              ___
Constraints:        ___
Dependencies:       ___
Rules:              ___
Policies:           ___
Failure Modes:      ___
Recovery:           ___
KPIs:               ___
Observability:      ___
Assumptions:        ___
Not Modeled:        ___
```
