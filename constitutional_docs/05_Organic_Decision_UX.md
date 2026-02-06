# Organic Decision UX

How decisions surface to users in a constraint-driven simulation.
Decisions are never prewritten. They are constructed at runtime from system state.

```
STATE + CONSTRAINTS + ACTION VERBS → DECISION SPACE
```

AI does not invent rules. AI translates the decision space into human-usable form.

---

## Layer Roles

### L0 — Truth Engine
Produces: system state, pressures, shortages, degradation, timers, dependencies, constraints.
Does not produce: decision menus, recommendations, narratives.

### AI Moderator
Produces: situation framing, surfaced options (derived, not scripted), consequence previews, uncertainty notes.
Does not: change rules, alter outcomes, inject mechanics, override constraints.

### UX Layer
Produces: decision cards, tradeoff displays, time horizons, confidence indicators.
Does not: execute actions, store state, generate options.

---

## Decision Generation Pipeline

### Step 1 — Detect Pressure
Pressure = any variable approaching a constraint boundary.

Detected automatically from the Constraint Registry (see Architecture Template §6):
- Capacity approaching limit
- Reserve below threshold
- Timer entering risk window
- Queue exceeding tolerance
- Redundancy lost
- Dependency degraded

Pressures are objects with severity, time horizon, and affected entities.

### Step 2 — Extract Active Constraints
What limits action right now:
- Resource availability
- Time remaining
- Dependency requirements
- Access / routing limits
- Crew / skill availability
- Policy restrictions

### Step 3 — Apply Action Verbs
Cross-reference affected entities with the Action Primitive Catalog.
Only verbs that pass constraint pre-checks are valid.

### Step 4 — Construct Options
Combine: `target entities × valid verbs × current constraints`

**Example:**
Pressure: Hospital power at risk.
Valid actions under current constraints:
- `allocate_resource(hospital, fuel, available_amount)`
- `reroute_flow(grid_feed, alternate_path)`
- `shed_load(non_critical_district, amount)`
- `delay_task(scheduled_maintenance)`
- `dispatch_supply(fuel, hospital)`

These become decision cards — not because someone wrote them, but because the state produced them.

---

## Decision Cards

No A/B/C buttons. Decision cards are dynamic, generated from state.

Each card contains:

| Field | Content |
|-------|---------|
| Situation | What pressure triggered this card |
| Time horizon | How long before the pressure becomes critical |
| Systems affected | What entities are involved |
| Action | Plain-language description of the verb bundle |
| Main benefit | What improves |
| Main tradeoff | What gets worse |
| Resource cost | What is consumed |
| Confidence | How certain is the projected outcome |
| Uncertainty | What data is missing or delayed |

Cards appear and disappear as state changes. They are not persistent menu items.

---

## AI Moderator Outputs

**Situation Brief:** Plain-language summary of current pressures, ranked by severity and time urgency.

**Option Surface:** Derived action possibilities — presented as decision cards. These are proposals, not commands.

**Consequence Preview:** Range-based projections for each option:
- Likely effect (high confidence band)
- Possible side effects (medium confidence)
- Uncertainty range (low confidence / missing data)

**Tradeoff Notes:** Explicit statement of what worsens if the selected option improves the target pressure.

**Uncertainty Flags:** What data is incomplete, delayed, or inferred. Marked on every relevant card.

---

## User Interaction

Users do not select from fixed story choices.
Users perform verbs on targets.

**Pattern:** Select Target → Select Verb → Confirm Action

**Example:** Hospital H2 → Allocate → Fuel Convoy

The selection maps to an Action Contract, validated by the engine before execution.

---

## Time Advancement

Time advances in decision cycles:

1. State updates (tick executes)
2. Pressures detected (constraint monitoring)
3. Decision cards generated (AI moderator)
4. Situation briefed (AI narration)
5. User acts (verb on target)
6. Contract validated and executed (engine)
7. Consequences propagate (next tick)

Each cycle is a complete loop. No action is required — the user can also observe and let time pass.

---

## Information Imperfection

This is a core feature, not optional. It creates the most interesting decision tension.

**Three visibility layers:**

| Layer | What It Contains | Who Sees It |
|-------|-----------------|-------------|
| Truth State | Full internal state (all values exact) | Engine only |
| Observed State | Delayed, partial, possibly stale data | AI moderator + user |
| Narrated State | AI interpretation of observed data | User |

**Information degradation types:**
- **Delay:** Data is N ticks old
- **Noise:** Value has ± error margin
- **Missing:** No telemetry from this entity
- **Inferred:** Value estimated from indirect signals

AI moderator marks every data point with its reliability:
- Direct observation (high confidence)
- Delayed observation (medium, with staleness noted)
- Inferred from related data (low, with inference chain noted)
- Unknown (flagged explicitly)

**Per-subsystem information config:**
Each subsystem defines its telemetry characteristics:
```
telemetry_delay:    ticks (how stale is data)
telemetry_noise:    float (± error range)
telemetry_coverage: percent (what fraction of assets report)
telemetry_cost:     resource (what monitoring costs)
```

Better information costs resources. This creates a monitoring vs. action tradeoff.

---

## Tension Mechanics

Organic tension emerges from structural constraints, not scripted drama:

- **Limited action slots per cycle** — can't do everything
- **Limited resources** — spending here means not spending there
- **Conflicting pressures** — fixing one thing worsens another
- **Delayed consequences** — effects arrive ticks later
- **Imperfect information** — acting on stale or incomplete data
- **Irreversible losses** — some failures can't be undone
- **Cascading dependencies** — one failure triggers others

If these mechanics are working, tension is emergent. If you need to script tension, the underlying systems are too simple.

---

## Failure UX — When Actions Are Rejected

When the engine rejects a user's selected action:

1. **State what was attempted** — "You tried to allocate fuel to Hospital H2"
2. **State why it failed** — "Fuel reserves are below the emergency minimum (constraint: strategic_reserve_floor)"
3. **State what would make it work** — "This action becomes available when fuel reserves exceed 2,000L"
4. **Offer alternatives** — AI recomputes valid options given current state

This must feel informative, not punitive. The user should think "I understand why that didn't work" — not "the game said no."

---

## AI Guardrails

**AI moderator must not:**
- Create new mechanics or rules
- Override constraints for dramatic effect
- Invent capabilities entities don't have
- Force outcomes the engine didn't produce
- Script decision sequences
- Suppress information to create artificial tension

**AI moderator may:**
- Summarize complex state in plain language
- Surface options derived from valid primitives
- Project consequence ranges
- Explain tradeoffs
- Highlight risks and uncertainties
- Rank options by urgency (with explanation)

---

## Success Criteria

The UX is working if users say:
- "The choices felt real."
- "The options made sense for the situation."
- "The AI helped me understand, not decide for me."
- "I wasn't picking from a script — I was responding to reality."

---

## Design Test

Remove all prewritten decisions. If the system still produces meaningful choices — the model is organic.

If removing scripts breaks decisions — you built a decision tree, not an organic system.
